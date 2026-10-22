from __future__ import annotations

import json
from asyncio import Lock
from asyncio import timeout as asyncio_timeout
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING, Self, cast, override
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from asyncpg import Connection, InterfaceError, PostgresError
from asyncpg import connect as asyncpg_connect

from forbql.engines._describe import Relation, assemble

# The engine's building blocks come from their own modules, not from the package:
# forbql.engines imports this subpackage through connect(), which would be a cycle.
from forbql.engines._errors import ErrorClass, QueryError
from forbql.engines._privileges import PrivilegeReport
from forbql.engines._protocol import QueryEngine, Restriction
from forbql.engines._result import Collector, ResultSet
from forbql.firewall import ForeignKey, SchemaCatalog
from forbql.policy import Engine, Limits

from ._catalog import COLUMNS, KEYS, RELATIONS, column_info
from ._privileges import ATTRIBUTES, REFUSALS, WARNINGS

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable

_PREFETCH_LIMIT = 200
"""Prefetch limit for PostgreSQL."""

_GRACE_SECONDS = 1.0
"""Grace period before prefetching again for PostgreSQL."""


_SETTINGS = """
SELECT set_config('statement_timeout', $1, true),
       set_config('lock_timeout', $1, true),
       set_config('search_path', $2, true)
"""
"""SQL to set the settings for PostgreSQL."""

_LOST = (InterfaceError, OSError)
"""Failures of the connection itself rather than of the query."""

_SCHEMES = frozenset({"postgres", "postgresql"})
"""URL schemes asyncpg accepts."""

_PASSTHROUGH = frozenset({"require", "verify-ca", "verify-full"})
"""sslmode values that encrypt. They are passed through, not upgraded."""

_FALLBACK = frozenset({"allow", "prefer"})
"""sslmode values that can send the session in clear."""


def driver_dsn(dsn: str) -> str:
    """Drop `forbql-insecure` and refuse a TLS mode that can fall back to clear.

    A URL or a libpq key=value string must set `sslmode`. `require`,
    `verify-ca`, and `verify-full` pass through. `prefer` and `allow` are
    refused. `disable` is plaintext only together with `forbql-insecure=1`,
    and that parameter is removed so asyncpg never sees it.

    Args:
        dsn: str - The DSN `connect` was given.

    Returns:
        str - The DSN asyncpg should open.

    """
    parts = urlsplit(dsn)
    if parts.scheme in _SCHEMES:
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        kept = _secured(pairs)
        if kept is None:
            return dsn
        query = urlencode(kept, quote_via=quote, safe="/:@")
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, query, parts.fragment),
        )
    kept = _secured(_conninfo(dsn))
    if kept is None:
        return dsn
    return _format_conninfo(kept)


def _secured(pairs: list[tuple[str, str]]) -> list[tuple[str, str]] | None:
    """Apply the sslmode rules and drop the opt-in flag.

    Args:
        pairs: list[tuple[str, str]] - DSN parameters, in order. The last value
            of a repeated key is the one that counts.

    Returns:
        list[tuple[str, str]] | None - The parameters asyncpg should see, or
            None when `pairs` is already in that form.

    """
    mode = _last(pairs, "sslmode")
    insecure = _last(pairs, "forbql-insecure") == "1"
    canonical = _require_sslmode(mode, insecure=insecure)
    if not _rewritten(pairs, canonical):
        return None
    return [
        (key, canonical if key == "sslmode" else value)
        for key, value in pairs
        if key != "forbql-insecure"
    ]


def _conninfo(dsn: str) -> list[tuple[str, str]]:
    """Parse a libpq key=value connection string.

    Args:
        dsn: str - `host=localhost dbname=bank sslmode=require`.

    Returns:
        list[tuple[str, str]] - Parameters, in order. A token that is not
            `key=value` is refused with the missing-`sslmode` error.

    """
    pairs: list[tuple[str, str]] = []
    index = 0
    length = len(dsn)
    while index < length:
        while index < length and dsn[index].isspace():
            index += 1
        if index >= length:
            break
        key, index = _conninfo_key(dsn, index)
        value, index = _conninfo_value(dsn, index)
        pairs.append((key, value))
    return pairs


def _conninfo_key(dsn: str, index: int) -> tuple[str, int]:
    """Read one parameter name.

    Args:
        dsn: str - The connection string.
        index: int - Where the name starts.

    Returns:
        tuple[str, int] - The name and the index just after `=`.

    Raises:
        ValueError: If this token is not `key=`.

    """
    start = index
    length = len(dsn)
    while index < length and dsn[index] not in "= \t\n":
        index += 1
    key = dsn[start:index]
    if not key or index >= length or dsn[index] != "=":
        msg = (
            "PostgreSQL DSN must set sslmode "
            "(require, verify-ca, or verify-full); "
            "sslmode=disable also needs forbql-insecure=1"
        )
        raise ValueError(msg)
    return key, index + 1


def _conninfo_value(dsn: str, index: int) -> tuple[str, int]:
    """Read one parameter value, quoted or bare.

    Args:
        dsn: str - The connection string.
        index: int - Where the value starts.

    Returns:
        tuple[str, int] - The value and the index just after it. A quoted value
            that never closes is an error.

    """
    if index < len(dsn) and dsn[index] == "'":
        return _quoted(dsn, index + 1)
    start = index
    while index < len(dsn) and not dsn[index].isspace():
        index += 1
    return dsn[start:index], index


def _quoted(dsn: str, index: int) -> tuple[str, int]:
    """Read a single-quoted libpq value.

    Args:
        dsn: str - The connection string.
        index: int - The index of the first character inside the quotes.

    Returns:
        tuple[str, int] - The unescaped value and the index just after the
            closing quote.

    Raises:
        ValueError: If the closing quote is missing.

    """
    characters: list[str] = []
    length = len(dsn)
    while index < length and dsn[index] != "'":
        if dsn[index] == "\\" and index + 1 < length:
            index += 1
        characters.append(dsn[index])
        index += 1
    if index >= length or dsn[index] != "'":
        msg = "PostgreSQL DSN has an unterminated quoted value"
        raise ValueError(msg)
    return "".join(characters), index + 1


def _format_conninfo(pairs: list[tuple[str, str]]) -> str:
    """Write parameters as a libpq connection string.

    Args:
        pairs: list[tuple[str, str]] - Parameters, in order.

    Returns:
        str - `key=value` pairs separated by spaces. A value that is empty or
            contains a space or quote is single-quoted.

    """
    written: list[str] = []
    for key, value in pairs:
        if value and not any(character in value for character in " '\t\n\\"):
            written.append(f"{key}={value}")
            continue
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        written.append(f"{key}='{escaped}'")
    return " ".join(written)


def _last(pairs: list[tuple[str, str]], key: str) -> str | None:
    """Return the last value of `key`, which is the one asyncpg would use."""
    found = [value for name, value in pairs if name == key]
    return found[-1] if found else None


def _require_sslmode(mode: str | None, *, insecure: bool) -> str:
    """Return the sslmode asyncpg should see.

    Args:
        mode: str | None - The DSN's `sslmode`, if it set one.
        insecure: bool - Whether the DSN opts in with `forbql-insecure=1`.

    Returns:
        str - The mode in lower case.

    Raises:
        ValueError: If the mode is missing, unknown, or falls back to cleartext.

    """
    if not mode:
        msg = (
            "PostgreSQL DSN must set sslmode "
            "(require, verify-ca, or verify-full); "
            "sslmode=disable also needs forbql-insecure=1"
        )
        raise ValueError(msg)
    canonical = mode.lower()
    if canonical in _FALLBACK:
        msg = f"sslmode={canonical} falls back to cleartext and is refused"
        raise ValueError(msg)
    if canonical == "disable":
        if not insecure:
            msg = "sslmode=disable requires forbql-insecure=1"
            raise ValueError(msg)
        return canonical
    if canonical not in _PASSTHROUGH:
        msg = f"unsupported sslmode: {mode}"
        raise ValueError(msg)
    return canonical


def _rewritten(pairs: list[tuple[str, str]], canonical: str) -> bool:
    """Whether the query has to be rebuilt before asyncpg sees it.

    Args:
        pairs: list[tuple[str, str]] - The DSN query, in order.
        canonical: str - The sslmode asyncpg should see.

    Returns:
        bool - True when `forbql-insecure` is present or `sslmode` is not already
            canonical.

    """
    return any(
        key == "forbql-insecure" or (key == "sslmode" and value != canonical)
        for key, value in pairs
    )


class PostgresEngine(QueryEngine):
    """A connection whose every query runs in a read-only transaction, then rolls back.

    Args:
        connection: asyncpg.Connection - Opened by `connect`.

    """

    _connection: Connection
    _lock: Lock
    """One operation at a time: asyncpg refuses a second one on the connection."""
    _search_path: str = "pg_catalog"
    """The search path for the PostgreSQL database."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self._lock = Lock()
        self._search_path = "pg_catalog"

    @property
    @override
    def engine(self) -> Engine:
        """The engine name.

        Returns:
            Engine.POSTGRES - The engine name.

        """
        return Engine.POSTGRES

    @classmethod
    async def connect(cls, dsn: str) -> Self:
        """Open a connection.

        A URL or a key=value string must set `sslmode`. `require`, `verify-ca`,
        and `verify-full` pass through. A missing mode, `prefer`, and `allow`
        raise `ValueError`. `disable` needs `forbql-insecure=1`, which is
        removed before asyncpg sees the DSN.

        Args:
            dsn: str - A `postgresql://` URL or key=value string.

        Returns:
            Self - The engine.

        Raises:
            QueryError: If the server is unreachable or refuses the login.

        """
        try:
            connection = await asyncpg_connect(driver_dsn(dsn))
        except (OSError, PostgresError) as error:
            raise QueryError(ErrorClass.CONNECTION, str(error)) from error
        return cls(connection)

    @override
    async def execute(self, sql: str, limits: Limits) -> ResultSet:
        """Run one query in a read-only transaction and roll it back.

        Args:
            sql: str - SQL regenerated by the firewall.
            limits: Limits - Time, row and byte bounds.

        Returns:
            ResultSet - The capped rows.

        """
        async with self._guarded():
            return await self._in_transaction(self._stream, sql, limits)

    @override
    async def estimate(self, sql: str, limits: Limits) -> float:
        """Ask the planner what the query would cost, without running it.

        Args:
            sql: str - SQL regenerated by the firewall.
            limits: Limits - Bounds; the time limit covers planning too.

        Returns:
            float - The plan's total cost, in the planner's units.

        """
        async with self._guarded():
            return await self._in_transaction(self._explain, sql, limits)

    @override
    async def describe(self) -> SchemaCatalog:
        """Read every table and view the role may select from, with keys and comments.

        Returns:
            SchemaCatalog - The catalog; the default schema is the head of the role's
                search path.

        """
        async with self._guarded(), self._connection.transaction(readonly=True):
            current = cast(
                "str",
                await self._connection.fetchval("SELECT current_schema()"),
            )
            _ = await self._connection.execute("SET LOCAL search_path = pg_catalog")
            columns = await self._connection.fetch(COLUMNS)
            relations = await self._connection.fetch(RELATIONS)
            keys = await self._connection.fetch(KEYS)
        found: dict[str, Relation] = {}
        for schema, table, comment, view, definition in relations:  # pyright: ignore[reportAny]
            found[f"{schema}.{table}"] = Relation(
                comment=cast("str | None", comment),
                view=cast("bool", view),
                definition=cast("str | None", definition),
            )
        for row in columns:
            schema, table, name, kind, nullable, comment, generated, expression = row  # pyright: ignore[reportAny]
            found[f"{schema}.{table}"].columns.append(
                column_info(
                    cast("str", name),
                    cast("str", kind),
                    cast("str | None", comment),
                    nullable=cast("bool", nullable),
                    generation=(
                        cast("bool", generated),
                        cast("str | None", expression),
                    ),
                ),
            )
        for schema, table, kind, own, ref_schema, ref_table, theirs in keys:  # pyright: ignore[reportAny]
            relation = found[f"{schema}.{table}"]
            if kind == "p":
                relation.primary_key = tuple(cast("list[str]", own))
            else:
                relation.foreign_keys.append(
                    ForeignKey(
                        columns=tuple(cast("list[str]", own)),
                        table=f"{ref_schema}.{ref_table}",
                        references=tuple(cast("list[str]", theirs)),
                    ),
                )
        catalog = assemble(current, found)
        schemas = sorted({name.split(".")[0] for name in catalog.tables})
        self._search_path = ", ".join(["pg_catalog", *map(self._quote, schemas)])
        return catalog

    @override
    async def check_privileges(self) -> PrivilegeReport:
        """Find what the role may do beyond reading.

        Returns:
            PrivilegeReport - Refusals and warnings; a superuser gets one refusal.

        """
        async with self._guarded(), self._connection.transaction(readonly=True):
            _ = await self._connection.execute("SET LOCAL search_path = pg_catalog")
            return await self._privilege_report()

    @override
    async def restrict(self, _restriction: Restriction, /) -> None:
        """Nothing to do: the database role enforces what it may read."""

    @override
    async def close(self) -> None:
        """Close the connection."""
        async with self._lock:
            await self._connection.close()

    @asynccontextmanager
    async def _guarded(self) -> AsyncGenerator[None]:
        """Hold the connection, and turn driver failures into query errors.

        Yields:
            None - While the caller uses the connection.

        Raises:
            QueryError: If the database refuses or fails, or time runs out.

        """
        async with self._lock:
            try:
                yield
            except PostgresError as error:
                raise QueryError(*self._classify_error(error)) from error
            except TimeoutError as error:
                raise QueryError(ErrorClass.TIMEOUT, str(error)) from error
            except _LOST as error:
                raise QueryError(ErrorClass.CONNECTION, str(error)) from error

    async def _privilege_report(self) -> PrivilegeReport:
        """Ask the check's questions inside the caller's transaction.

        Returns:
            PrivilegeReport - Refusals and warnings.

        """
        attributes = await self._findings((ATTRIBUTES,))
        if "the role has SUPERUSER" in attributes:
            return PrivilegeReport(refusals=("the role has SUPERUSER",))
        return PrivilegeReport(
            refusals=attributes + await self._findings(REFUSALS),
            warnings=await self._findings(WARNINGS),
        )

    async def _findings(self, queries: tuple[str, ...]) -> tuple[str, ...]:
        """Run queries that return one text column; each row is one finding.

        Args:
            queries: tuple[str, ...] - The queries.

        Returns:
            tuple[str, ...] - The findings, in query order.

        """
        found: list[str] = []
        for query in queries:
            records = await self._connection.fetch(query)
            found.extend(str(cast("str", record[0])) for record in records)
        return tuple(found)

    async def _in_transaction[T](
        self,
        work: Callable[[str, Limits], Awaitable[T]],
        sql: str,
        limits: Limits,
    ) -> T:
        """Do the work inside a read-only transaction with the limits, then roll back.

        Args:
            work: Callable[[str, Limits], Awaitable[T]] - Streams or explains the query.
            sql: str - SQL regenerated by the firewall.
            limits: Limits - Time, row and byte bounds.

        Returns:
            T - What the work returned.

        """
        transaction = self._connection.transaction(readonly=True)
        await transaction.start()
        try:
            timeout = str(limits.statement_timeout_ms)
            _ = await self._connection.execute(_SETTINGS, timeout, self._search_path)
            return await work(sql, limits)
        finally:
            # A lost connection must not hide the error that lost it.
            with suppress(PostgresError, *_LOST):
                await transaction.rollback()

    async def _stream(self, sql: str, limits: Limits) -> ResultSet:
        """Stream the results of a query.

        Args:
            sql: str - SQL regenerated by the firewall.
            limits: Limits - Time, row and byte bounds.

        Returns:
            ResultSet - The capped rows.
        """
        collector = Collector(limits)
        async with asyncio_timeout(limits.statement_timeout_ms / 1000 + _GRACE_SECONDS):
            statement = await self._connection.prepare(sql)
            columns = [attr.name for attr in statement.get_attributes()]
            async for record in statement.cursor(prefetch=_PREFETCH_LIMIT):
                if not collector.add(tuple(record.values())):
                    break

        return collector.result(columns)

    async def _explain(self, sql: str, _limits: Limits) -> float:
        """Read the total cost of the query's plan.

        Args:
            sql: str - SQL regenerated by the firewall.
            _limits: Limits - Unused; the transaction already applies them.

        Returns:
            float - The plan's total cost.

        """
        plan = cast(
            "str",
            await self._connection.fetchval(f"EXPLAIN (FORMAT JSON) {sql}"),
        )
        return float(json.loads(plan)[0]["Plan"]["Total Cost"])  # pyright: ignore[reportAny]

    @classmethod
    def _quote(cls, name: str) -> str:
        return '"' + name.replace('"', '""') + '"'

    @classmethod
    def _classify_error(cls, error: PostgresError) -> tuple[ErrorClass, str]:
        state = str(getattr(error, "sqlstate", "") or "")
        text = str(error)
        if state == "57014":
            return ErrorClass.TIMEOUT, text
        if state == "42501":
            return ErrorClass.PERMISSION_DENIED, text
        if state == "25006":
            return ErrorClass.READ_ONLY, text
        if state.startswith(("42", "22")):
            return ErrorClass.INVALID_QUERY, text
        if state.startswith("08"):
            return ErrorClass.CONNECTION, text
        return ErrorClass.DATABASE, text
