"""A session: the firewall, a read-only engine, masking and the audit log, in order."""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING

from forbql.audit import Action, AuditLog, AuditSink
from forbql.engines import QueryEngine, QueryError, Restriction, ResultSet
from forbql.engines import connect as connect_engine
from forbql.firewall import Firewall
from forbql.knowledge import LIMIT, diff_catalogs
from forbql.masking import apply_masks
from forbql.policy import Policy, load_policy
from forbql.session._config import ForbqlSettings, SessionError, mask_key

from ._cost import COST_HINTS, CostDecision, decide
from ._knowledge import Knowledge, default_embedder
from ._store import find_dsn, open_store

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from forbql.engines import ErrorClass
    from forbql.firewall import SchemaCatalog, Verdict
    from forbql.knowledge import Embedder, SearchResult
    from forbql.policy import ExplainThresholds, Limits
    from forbql.store import Store


type _Row = tuple[object, ...]


@dataclass(frozen=True, slots=True)
class RunResult:
    """What one `run` produced.

    Attributes:
        verdict: Verdict - The firewall's verdict.
        columns: tuple[str, ...] - Output column names.
        rows: tuple[Row, ...] - Masked rows.
        truncated: bool - Whether a cap cut the result.
        error: ErrorClass | None - Database failure class, if the database failed.
        hint: str | None - What to do about the failure or the stop.
        cost: float | None - The planner's estimate; None where the engine has none.
        decision: CostDecision - Whether the estimate let the query run.

    """

    verdict: Verdict
    columns: tuple[str, ...] = ()
    rows: tuple[_Row, ...] = ()
    truncated: bool = False
    error: ErrorClass | None = None
    hint: str | None = None
    cost: float | None = None
    decision: CostDecision = CostDecision.OK

    @property
    def ok(self) -> bool:
        """Whether the call was allowed, ran, and completed."""
        return (
            self.verdict.allowed
            and self.error is None
            and self.decision is CostDecision.OK
        )


@dataclass(frozen=True, slots=True)
class Diagnosis:
    """What the startup checks found for one profile of one connection.

    Attributes:
        refusals: tuple[str, ...] - Findings that keep a session from opening: rights
            beyond reading, views calling functions the profile may not.
        warnings: tuple[str, ...] - Findings worth fixing that break no guarantee.

    """

    refusals: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """Whether a session may open: nothing was refused."""
        return not self.refusals


@dataclass(frozen=True, slots=True)
class _Target:
    connection: str
    profile: str
    principal: str
    limits: Limits
    explain: ExplainThresholds


class Session:
    """Runs queries for one profile of one connection. Build it with `connect`.

    Args:
        target: _Target - Who asks, where, within which limits.
        firewall: Firewall - Checks each query.
        engine: QueryEngine - Runs checked queries read-only.
        audit: AuditSink - Records every call.
        key: bytes | None - HMAC key for the `hash` strategy.
        warnings: tuple[str, ...] - What the startup checks advise fixing.
        knowledge: Knowledge | None - The synced schema and its index; None
            without a store.

    """

    _target: _Target
    _firewall: Firewall
    _engine: QueryEngine
    _audit: AuditSink
    _key: bytes | None
    _warnings: tuple[str, ...]
    _knowledge: Knowledge | None

    def __init__(  # ruff: ignore[too-many-arguments] - the parts connect() assembles
        self,
        target: _Target,
        firewall: Firewall,
        engine: QueryEngine,
        audit: AuditSink,
        key: bytes | None,
        *,
        warnings: tuple[str, ...] = (),
        knowledge: Knowledge | None = None,
    ) -> None:
        self._target = target
        self._firewall = firewall
        self._engine = engine
        self._audit = audit
        self._key = key
        self._warnings = warnings
        self._knowledge = knowledge

    @property
    def warnings(self) -> tuple[str, ...]:
        """What the startup checks advise fixing; none of it breaks a guarantee."""
        return self._warnings

    async def search(self, question: str, *, limit: int = LIMIT) -> SearchResult:
        """Find the tables, glossary terms and examples a question needs.

        Only what the profile may see takes part: tables and columns it sees, terms
        and examples whose SQL passes its firewall and whose text names nothing
        hidden from it.

        Args:
            question: str - What the caller asks, in any language.
            limit: int - Tables to return.

        Returns:
            SearchResult - Tables, each match followed by those it joins; terms and
                examples, best first.

        Raises:
            SessionError: If there is no store to search.

        """
        start = monotonic()
        if self._knowledge is None:
            await self._note(Action.SCHEMA_SEARCH, question, start, refused="no_store")
            msg = "schema search needs the store: set FORBQL_STORE_DSN"
            raise SessionError(msg)
        found = await self._knowledge.search(
            self._firewall,
            connection=self._target.connection,
            profile=self._target.profile,
            question=question,
            limit=limit,
        )
        shown = len(found.tables) + len(found.glossary) + len(found.examples)
        await self._note(Action.SCHEMA_SEARCH, question, start, rows=shown)
        return found

    async def check(self, sql: str) -> Verdict:
        """Check a query against the firewall without running it; the call is audited.

        Args:
            sql: str - The query as the caller wrote it.

        Returns:
            Verdict - The firewall's verdict.

        """
        start = monotonic()
        verdict = self._verdict(sql)
        await self._record(sql, verdict, start, action=Action.SQL_CHECK)
        return verdict

    def _verdict(self, sql: str) -> Verdict:
        """Ask the firewall about a query for this profile.

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

    async def run(self, sql: str, *, confirmed: bool = False) -> RunResult:
        """Check, estimate, run read-only, mask, audit. Every call leaves a record.

        Args:
            sql: str - The query as the caller wrote it.
            confirmed: bool - Run it even if the estimate reaches `confirm_cost`.

        Returns:
            RunResult - Rows, or the rejection, the stop, or the database failure.

        """
        start = monotonic()
        verdict = self._verdict(sql)
        if not verdict.allowed or verdict.sql is None:
            await self._record(sql, verdict, start)
            return RunResult(verdict)

        cost: float | None = None
        try:
            cost = await self._engine.estimate(verdict.sql, self._target.limits)
            decision = decide(cost, self._target.explain, confirmed=confirmed)
            if decision is not CostDecision.OK:
                return await self._stop(sql, verdict, start, cost, decision)
            result = await self._engine.execute(verdict.sql, self._target.limits)
        except QueryError as err:
            await self._record(sql, verdict, start, error=err)
            return RunResult(verdict, error=err.error_class, hint=err.hint, cost=cost)

        rows = apply_masks(result.rows, verdict.masks, self._key)
        await self._record(sql, verdict, start, result=result)
        return RunResult(
            verdict,
            columns=result.columns,
            rows=rows,
            truncated=result.truncated,
            cost=cost,
        )

    async def _stop(
        self,
        sql: str,
        verdict: Verdict,
        start: float,
        cost: float | None,
        decision: CostDecision,
    ) -> RunResult:
        """Record a query the estimate stopped, and tell the caller why.

        Args:
            sql: str - The query as the caller wrote it.
            verdict: Verdict - The firewall's verdict; it allowed the query.
            start: float - When the call began, on the monotonic clock.
            cost: float | None - The estimate.
            decision: CostDecision - Confirm or block.

        Returns:
            RunResult - No rows; the decision and a hint.

        """
        await self._record(sql, verdict, start, stopped=decision, cost=cost)
        hint = COST_HINTS[decision]
        return RunResult(verdict, hint=hint, cost=cost, decision=decision)

    async def _record(  # ruff: ignore[too-many-arguments] - one keyword per outcome
        self,
        sql: str,
        verdict: Verdict,
        start: float,
        *,
        action: Action = Action.SQL_RUN,
        result: ResultSet | None = None,
        error: QueryError | None = None,
        stopped: CostDecision | None = None,
        cost: float | None = None,
    ) -> None:
        failure, detail = None, None
        if error is not None:
            failure, detail = error.error_class.value, error.detail
        elif stopped is not None:
            failure, detail = f"cost_{stopped}", f"estimated cost {cost}"
        ran = action is Action.SQL_RUN and stopped is None
        await self._append(
            action,
            sql,
            start,
            executed_sql=verdict.sql if ran else None,
            allowed=verdict.allowed,
            rules=tuple(violation.rule.value for violation in verdict.violations),
            rows=len(result.rows) if result else 0,
            size=result.size if result else 0,
            truncated=result.truncated if result else False,
            error_class=failure,
            error_detail=detail,
        )

    async def _note(
        self,
        action: Action,
        asked: str,
        start: float,
        *,
        rows: int = 0,
        refused: str | None = None,
    ) -> None:
        """Record a call that ran no query: a search, a description, a read.

        Args:
            action: Action - What kind of call.
            asked: str - What the caller sent: a question, a table, a resource.
            start: float - When the call began, on the monotonic clock.
            rows: int - Items returned.
            refused: str | None - Why the call was refused; None when it answered.

        """
        await self._append(
            action,
            asked,
            start,
            executed_sql=None,
            allowed=refused is None,
            rules=(),
            rows=rows,
            size=0,
            truncated=False,
            error_class=refused,
            error_detail=None,
        )

    async def _append(
        self,
        action: Action,
        asked: str,
        start: float,
        **outcome: object,
    ) -> None:
        """Write the record of a call with who made it, where, and under which policy.

        Args:
            action: Action - What kind of call.
            asked: str - What the caller sent.
            start: float - When the call began, on the monotonic clock.
            **outcome: object - The rest of the record's fields.

        """
        _ = await self._audit.append(
            principal=self._target.principal,
            connection=self._target.connection,
            profile=self._target.profile,
            action=action,
            policy_hash=self._firewall.policy_hash,
            sql=asked,
            duration_ms=round((monotonic() - start) * 1000),
            **outcome,
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
    embedder: Embedder | None = None,
) -> AsyncGenerator[Session, None]:
    """Open a session: connect, read the schema, restrict, and hand over.

    Args:
        policy: Policy | str | Path - The policy, or the path to its file.
        connection: str - Connection name in the policy.
        profile: str - Profile name.
        dsn: str | None - DSN; defaults to the store's, or without a store to the
            `FORBQL_DSN_<CONNECTION>` variable.
        audit_log: str | Path | None - JSON Lines file every call is recorded in;
            defaults to the store's chain, or without a store to `FORBQL_AUDIT_LOG`,
            else `forbql-audit.jsonl`.
        principal: str - Who is calling, as the audit log records it.
        embedder: Embedder | None - The model schema search uses; the index must
            have been built with the same one.

    Yields:
        Session - The session; the connection closes when the block ends.

    Raises:
        SessionError: If the DSN or mask key is missing, the DSN is malformed, the
            engine's extra is not installed, the database cannot be read, the store
            refuses, or the startup checks refuse the role or a view.

    """
    settings = ForbqlSettings()
    loaded = policy if isinstance(policy, Policy) else load_policy(policy)
    chosen = loaded.profile(connection, profile)
    key = mask_key(chosen, settings)
    async with AsyncExitStack() as stack:
        store = await open_store(stack, settings)
        found = await find_dsn(
            store,
            settings,
            policy=loaded,
            connection=connection,
            profile=profile,
            dsn=dsn,
        )
        engine = await open_engine(loaded, connection, found)
        _ = stack.push_async_callback(engine.close)
        firewall, diagnosis, reviewed = await _inspect(
            engine,
            loaded,
            connection,
            profile,
            store,
        )
        if diagnosis.refusals:
            found = "\n".join(f"  - {line}" for line in diagnosis.refusals)
            msg = f"forbql will not open {connection} for {profile}:\n{found}"
            raise SessionError(msg)
        await engine.restrict(
            Restriction(
                tables=firewall.visible(connection, profile),
                functions=frozenset(chosen.functions.allow),
                allow_recursive=chosen.allow_recursive_cte,
            ),
        )
        target = _Target(connection, profile, principal, chosen.limits, chosen.explain)
        log: AuditSink = AuditLog(Path(audit_log or settings.audit_log))
        if store is not None and audit_log is None:
            log = store.audit
        yield Session(
            target,
            firewall,
            engine,
            log,
            key,
            warnings=diagnosis.warnings,
            knowledge=Knowledge(
                store,
                reviewed,
                embedder or default_embedder(),
                loaded.connection(connection).engine,
            )
            if store is not None and reviewed is not None
            else None,
        )


async def diagnose(
    policy: Policy | str | Path,
    *,
    connection: str,
    profile: str,
    dsn: str | None = None,
) -> Diagnosis:
    """Run the startup checks for a profile without opening a session.

    Failing to reach or read the database raises `SessionError`, as `connect` does.

    Args:
        policy: Policy | str | Path - The policy, or the path to its file.
        connection: str - Connection name in the policy.
        profile: str - Profile name.
        dsn: str | None - DSN; found as `connect` finds it when not given.

    Returns:
        Diagnosis - What `connect` would refuse and what it would warn about.

    """
    settings = ForbqlSettings()
    loaded = policy if isinstance(policy, Policy) else load_policy(policy)
    _ = loaded.profile(connection, profile)
    async with AsyncExitStack() as stack:
        store = await open_store(stack, settings)
        found = await find_dsn(
            store,
            settings,
            policy=loaded,
            connection=connection,
            profile=profile,
            dsn=dsn,
        )
        engine = await open_engine(loaded, connection, found)
        _ = stack.push_async_callback(engine.close)
        _, diagnosis, _ = await _inspect(engine, loaded, connection, profile, store)
    return diagnosis


async def open_engine(policy: Policy, connection: str, dsn: str) -> QueryEngine:
    """Open the connection's engine, turning every way it can fail into one error.

    Args:
        policy: Policy - The policy; it names the engine.
        connection: str - Connection name in the policy.
        dsn: str - The DSN.

    Returns:
        QueryEngine - The open engine.

    Raises:
        SessionError: If the DSN is malformed, the engine's extra is not installed,
            or the database is unreachable.

    """
    try:
        return await connect_engine(policy.connection(connection).engine, dsn)
    except QueryError as err:
        msg = f"failed to connect to {connection}: {err.hint}"
        raise SessionError(msg) from err
    except (ImportError, ValueError) as err:
        msg = f"failed to connect to {connection}: {err}"
        raise SessionError(msg) from err


async def _inspect(
    engine: QueryEngine,
    policy: Policy,
    connection: str,
    profile: str,
    store: Store | None,
) -> tuple[Firewall, Diagnosis, SchemaCatalog | None]:
    """Read the schema and run the startup checks.

    With a store, the firewall sees only what is both in the database now and in the
    snapshot the operator synced last; a change since then is a warning.

    Args:
        engine: QueryEngine - The open engine.
        policy: Policy - The policy.
        connection: str - Connection name in the policy.
        profile: str - Profile name.
        store: Store | None - The store, if one is configured.

    Returns:
        tuple[Firewall, Diagnosis, SchemaCatalog | None] - The firewall over the
            schema, the findings, and the schema synced last if there is one.

    Raises:
        SessionError: If the database cannot be read.

    """
    try:
        report = await engine.check_privileges()
        live = await engine.describe()
    except QueryError as err:
        msg = f"failed to read the schema of {connection}: {err.hint}"
        raise SessionError(msg) from err
    snapshot, refusals, warnings = live.snapshot(), report.refusals, report.warnings
    catalog = None
    if store is not None:
        reviewed = await store.snapshots.latest(connection)
        if reviewed is None:
            sync = f"run `forbql schema sync {connection}`"
            refusals += (f"the store has no reviewed schema of {connection}: {sync}",)
        else:
            catalog = reviewed.catalog
            snapshot = snapshot.within(catalog.snapshot())
            if changes := diff_catalogs(reviewed.catalog, live):
                count = f"{len(changes)} changes, unseen until synced"
                see = f"see `forbql schema diff {connection}`"
                warnings += (
                    f"{connection} changed since the last sync ({count}): {see}",
                )
    firewall = Firewall(policy, {connection: snapshot})
    views = tuple(
        f"view {name}: {violation.message}"
        for name, violations in firewall.check_views(connection, profile).items()
        for violation in violations
    )
    diagnosis = Diagnosis(refusals=refusals + views, warnings=warnings)
    return firewall, diagnosis, catalog
