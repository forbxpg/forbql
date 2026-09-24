"""A session: the firewall, a read-only engine, masking and the audit log, in order."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING

from forbql.audit import AuditLog
from forbql.engines import QueryEngine, QueryError, Restriction, ResultSet
from forbql.engines import connect as connect_engine
from forbql.firewall import Firewall
from forbql.masking import apply_masks
from forbql.policy import Policy, load_policy
from forbql.session._config import ForbqlSettings, SessionError, mask_key, resolve_dsn

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from forbql.engines import ErrorClass
    from forbql.firewall import Verdict
    from forbql.policy import Limits


type __Row = tuple[object, ...]


@dataclass(frozen=True, slots=True)
class RunResult:
    """What one `run` produced.

    Attributes:
        verdict: Verdict - The firewall's verdict.
        columns: tuple[str, ...] - Output column names.
        rows: tuple[Row, ...] - Masked rows.
        truncated: bool - Whether a cap cut the result.
        error: ErrorClass | None - Database failure class, if the database failed.
        hint: str | None - What to do about the failure.

    """

    verdict: Verdict
    columns: tuple[str, ...] = ()
    rows: tuple[__Row, ...] = ()
    truncated: bool = False
    error: ErrorClass | None = None
    hint: str | None = None

    @property
    def ok(self) -> bool:
        """Whether the call was allowed and completed."""
        return self.verdict.allowed and self.error is None


@dataclass(frozen=True, slots=True)
class _Target:
    connection: str
    profile: str
    principal: str
    limits: Limits


class Session:
    """Runs queries for one profile of one connection. Build it with `connect`.

    Args:
        target: _Target - Who asks, where, within which limits.
        firewall: Firewall - Checks each query.
        engine: QueryEngine - Runs checked queries read-only.
        audit: AuditLog - Records every call.
        key: bytes | None - HMAC key for the `hash` strategy.

    """

    _target: _Target
    _firewall: Firewall
    _engine: QueryEngine
    _audit: AuditLog
    _key: bytes | None

    def __init__(
        self,
        target: _Target,
        firewall: Firewall,
        engine: QueryEngine,
        audit: AuditLog,
        key: bytes | None,
    ) -> None:
        self._target = target
        self._firewall = firewall
        self._engine = engine
        self._audit = audit
        self._key = key

    def check(self, sql: str) -> Verdict:
        """Check a query against the firewall.

        Args:
            sql: str - The query as the caller wrote it.

        Returns:
            Verdict - The firewall's verdict.
        """
        return self._firewall.check(
            sql,
            connection=self._target.connection,
            profile=self._target.profile,
        )

    async def run(self, sql: str) -> RunResult:
        """Check, run read-only, mask, audit. Every call leaves an audit record.

        Args:
            sql: str - The query as the caller wrote it.

        Returns:
            RunResult - Rows, or the rejection, or the database failure.

        """
        start = monotonic()
        verdict = self.check(sql)
        if not verdict.allowed or verdict.sql is None:
            self._record(sql, verdict, start)
            return RunResult(verdict)

        try:
            result = await self._engine.execute(verdict.sql, self._target.limits)
        except QueryError as err:
            self._record(sql, verdict, start, error=err)
            return RunResult(verdict, error=err.error_class, hint=err.hint)

        rows = apply_masks(result.rows, verdict.masks, self._key)
        self._record(sql, verdict, start, result=result)
        return RunResult(
            verdict,
            columns=result.columns,
            rows=rows,
            truncated=result.truncated,
        )

    def _record(
        self,
        sql: str,
        verdict: Verdict,
        start: float,
        *,
        result: ResultSet | None = None,
        error: QueryError | None = None,
    ) -> None:
        _ = self._audit.append(
            principal=self._target.principal,
            connection=self._target.connection,
            profile=self._target.profile,
            policy_hash=self._firewall.policy_hash,
            sql=sql,
            executed_sql=verdict.sql,
            allowed=verdict.allowed,
            rules=tuple(violation.rule.value for violation in verdict.violations),
            rows=len(result.rows) if result else 0,
            size=result.size if result else 0,
            truncated=result.truncated if result else False,
            duration_ms=round((monotonic() - start) * 1000),
            error_class=error.error_class.value if error else None,
            error_detail=error.detail if error else None,
        )


@asynccontextmanager
async def connect(  # ruff: ignore[too-many-arguments]
    policy: Policy | str | Path,
    *,
    connection: str,
    profile: str,
    dsn: str | None = None,
    audit_log: str | Path | None = None,
    principal: str = "local",
) -> AsyncGenerator[Session, None]:
    """Open a session: connect, read the schema, restrict, and hand over.

    Args:
        policy: Policy | str | Path - The policy, or the path to its file.
        connection: str - Connection name in the policy.
        profile: str - Profile name.
        dsn: str | None - DSN; defaults to the `FORBQL_DSN_<CONNECTION>` variable.
        audit_log: str | Path | None - JSON Lines file every call is recorded in;
            defaults to `FORBQL_AUDIT_LOG`, else `forbql-audit.jsonl`.
        principal: str - Who is calling, as the audit log records it.

    Yields:
        Session - The session; the connection closes when the block ends.

    Raises:
        SessionError: If the DSN or mask key is missing or the database is unreachable.

    """
    settings = ForbqlSettings()
    loaded = policy if isinstance(policy, Policy) else load_policy(policy)
    chosen = loaded.profile(connection, profile)
    key = mask_key(chosen, settings)
    kind = loaded.connection(connection).engine
    try:
        engine = await connect_engine(kind, resolve_dsn(connection, dsn, settings))
    except QueryError as err:
        msg = f"failed to connect to {connection}: {err.hint}"
        raise SessionError(msg) from err

    try:
        firewall = Firewall(loaded, {connection: await engine.snapshot()})
        await engine.restrict(
            Restriction(
                tables=firewall.visible(connection, profile),
                functions=frozenset(chosen.functions.allow),
                allow_recursive=chosen.allow_recursive_cte,
            ),
        )
        target = _Target(connection, profile, principal, chosen.limits)
        log = AuditLog(Path(audit_log or settings.audit_log))
        yield Session(target, firewall, engine, log, key)
    finally:
        await engine.close()
