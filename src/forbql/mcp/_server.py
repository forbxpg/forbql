"""The MCP server: five tools and three resources over one session.

The session opens on first use, not at start: a refusal (no synced schema, a role
that may write) reaches the model as the reason on every call, and once the
operator fixes it the next call opens without a restart.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import asdict
from typing import TYPE_CHECKING

import sqlglot
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ResourceError
from fastmcp.server.auth import require_scopes
from fastmcp.server.dependencies import get_access_token
from fastmcp.tools import ToolResult  # ruff: ignore[typing-only-third-party-import] - FastMCP reads tool annotations at runtime
from mcp.types import InputRequiredResult, ToolAnnotations

from forbql.access import Capability
from forbql.knowledge import LIMIT
from forbql.policy import PolicyError, UnknownProfileError
from forbql.session import CostDecision, SessionError

from ._auth import NEEDS, Capabilities, TokenGate
from ._confirm import confirm
from ._instructions import instructions
from ._limits import OneQueryEach, rate_limit
from ._output import ROWS, fit, reply, untrusted

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable
    from contextlib import AbstractAsyncContextManager

    from fastmcp.server.auth import AuthCheck

    from forbql.firewall import Verdict
    from forbql.policy import Engine, Policy
    from forbql.session import Gate, RunResult, Session

type Opener = Callable[[], AbstractAsyncContextManager[Session]]

_READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)

_PROPOSING = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
)
"""Proposing writes to forbql's queue, never to the database."""

_UNCONFIRMED = (
    "stopped: the person at the client did not confirm this expensive query; narrow it"
)

_UNASKED = "stopped: the planner expects this query to be expensive; narrow it"
"""Over HTTP by default nobody is asked: the client may be the agent's own code."""


class _Sessions:
    """The one session of this server, opened on first use and kept.

    Args:
        opener: Opener - Opens a session, as `forbql.connect` does.

    """

    _opener: Opener
    _stack: AsyncExitStack
    _session: Session | None
    _lock: asyncio.Lock

    def __init__(self, opener: Opener) -> None:
        self._opener = opener
        self._stack = AsyncExitStack()
        self._session = None
        self._lock = asyncio.Lock()

    async def get(self) -> Session:
        """Return the session, opening it if it is not open, for this request's caller.

        Returns:
            Session - The session; over HTTP, one that records the request's token.

        """
        async with self._lock:
            if self._session is None:
                self._session = await self._stack.enter_async_context(self._opener())
        token = get_access_token()
        return (
            self._session if token is None else self._session.acting_as(token.client_id)
        )

    async def close(self) -> None:
        """Close the session, if it opened."""
        await self._stack.aclose()


class _Tools:
    """The tools and resources, over the server's one session.

    Args:
        sessions: _Sessions - The session.
        engine: Engine - The connection's engine.
        max_rows: int - Rows a model receives at most.
        ask: bool - Whether the person at the client decides on expensive queries;
            without it they are stopped.

    """

    _sessions: _Sessions
    _engine: Engine
    _max_rows: int
    _ask: bool

    def __init__(
        self,
        sessions: _Sessions,
        engine: Engine,
        max_rows: int,
        *,
        ask: bool,
    ) -> None:
        self._sessions = sessions
        self._engine = engine
        self._max_rows = max_rows
        self._ask = ask

    async def search_schema(self, query: str, limit: int = LIMIT) -> ToolResult:
        """Find the tables, glossary terms and examples a question needs.

        Args:
            query: str - The question, in any language.
            limit: int - Tables to return.

        Returns:
            ToolResult - Tables with the columns you may use and the tables they
                join; terms and examples, best first.

        """

        async def work(session: Session) -> ToolResult:
            found = await session.search(query, limit=limit)
            counts = (
                f"{len(found.tables)} tables",
                f"{len(found.glossary)} glossary terms",
                f"{len(found.examples)} examples",
            )
            return reply(
                ", ".join(counts),
                {
                    "tables": [asdict(hit) for hit in found.tables],
                    "glossary": [term.model_dump() for term in found.glossary],
                    "examples": [example.model_dump() for example in found.examples],
                },
            )

        return await self._within(work)

    async def describe_table(self, table: str) -> ToolResult:
        """Show a table's columns, keys, joins and frequent values.

        Args:
            table: str - `schema.table`, or `table` in the default schema.

        Returns:
            ToolResult - Columns with types, keys and PII classes; join
                conditions to other tables; sample values where the policy allows.

        """

        async def work(session: Session) -> ToolResult:
            found = await session.describe(table)
            summary = f"{found.table}: {len(found.columns)} columns you may use"
            return reply(summary, asdict(found))

        return await self._within(work)

    async def check_sql(self, sql: str) -> ToolResult:
        """Check a query without running it.

        Args:
            sql: str - The query.

        Returns:
            ToolResult - Allowed, with the query as it would run; or why not.

        """

        async def work(session: Session) -> ToolResult:
            verdict = await session.check(sql)
            if not verdict.allowed:
                return reply(_rejection(verdict))
            return reply(_allowed("allowed", verdict), {"sql": verdict.sql})

        return await self._within(work)

    async def propose_example(self, question: str, sql: str) -> ToolResult:
        """Offer the operator an example for everyone's search: a question, its query.

        Propose a query that answered a question others will ask. Nothing runs; once
        the operator approves it, search_schema shows it.

        Args:
            question: str - The question, as a person would ask it.
            sql: str - The query that answers it.

        Returns:
            ToolResult - The proposal's number, or why it was refused.

        """

        async def work(session: Session) -> ToolResult:
            number = await session.propose(question, sql)
            return reply(f"proposed as {number}; the operator reviews it")

        return await self._within(work)

    async def run_sql(self, sql: str, ctx: Context) -> ToolResult | InputRequiredResult:
        """Run a query read-only and return its rows, masked and within budget.

        A rejection is an answer, not an error: it says what to change. A query the
        planner expects to be expensive runs only if the person at the client says
        yes.

        Args:
            sql: str - The query.
            ctx: Context - The call.

        Returns:
            ToolResult | InputRequiredResult - Rows, a rejection, a stop or a
                database error; or the question for the person.

        """
        try:
            session = await self._sessions.get()
        except (SessionError, PolicyError, UnknownProfileError) as err:
            return reply(f"forbql is not ready: {err}", error=True)
        result = await session.run(sql)
        if result.decision is CostDecision.CONFIRM and not self._ask:
            return reply(_UNASKED)
        if result.decision is CostDecision.CONFIRM and result.verdict.sql:
            answer = await confirm(
                ctx,
                message=_question(result, self._engine),
                query=result.verdict.sql,
            )
            if isinstance(answer, InputRequiredResult):
                return answer
            if not answer:
                return reply(_UNCONFIRMED)
            result = await session.run(sql, confirmed=True)
        return _ran(result, self._max_rows)

    async def erd(self) -> str:
        """Every table the profile sees as a Mermaid diagram; past 40, their names.

        Returns:
            str - The diagram, or the table names with a pointer to one table's.

        """
        drawn = await _read(self._sessions, lambda session: session.erd())
        if drawn.startswith("erDiagram"):
            return drawn
        return f"Too many tables for one diagram; read forbql://erd/{{table}}.\n{drawn}"

    async def erd_around(self, table: str) -> str:
        """One table and the tables it joins, as a Mermaid diagram.

        Args:
            table: str - `schema.table`, or `table` in the default schema.

        Returns:
            str - The diagram.

        """
        return await _read(self._sessions, lambda session: session.erd(table))

    async def glossary(self) -> str:
        """The glossary terms the profile may see, marked untrusted.

        Returns:
            str - The terms.

        """
        terms = await _read(self._sessions, lambda session: session.glossary())
        return untrusted([term.model_dump() for term in terms])

    async def _within(
        self,
        work: Callable[[Session], Awaitable[ToolResult]],
    ) -> ToolResult:
        """Run a tool's work in the session, turning refusals into answers.

        Args:
            work: Callable[[Session], Awaitable[ToolResult]] - The work.

        Returns:
            ToolResult - Its answer, or why there is none.

        """
        try:
            session = await self._sessions.get()
        except (SessionError, PolicyError, UnknownProfileError) as err:
            return reply(f"forbql is not ready: {err}", error=True)
        try:
            return await work(session)
        except SessionError as err:
            return reply(f"refused: {err}", error=True)


def build_server(  # ruff: ignore[too-many-arguments] - the profile, and how it is served
    policy: Policy,
    *,
    connection: str,
    profile: str,
    opener: Opener,
    gate: Gate | None = None,
    ask: bool = True,
) -> FastMCP:
    """Build the server for one profile of one connection.

    Args:
        policy: Policy - The policy; the instructions are written from it.
        connection: str - Connection name.
        profile: str - Profile name.
        opener: Opener - Opens the session the tools use.
        gate: Gate | None - Lets tokens in over HTTP; None over stdio, where the
            caller is the local user.
        ask: bool - Whether an expensive query goes to the person at the client;
            without it such a query is stopped.

    Returns:
        FastMCP - The server.

    """
    sessions = _Sessions(opener)
    tools = _Tools(
        sessions,
        policy.connection(connection).engine,
        min(ROWS, policy.profile(connection, profile).limits.max_rows),
        ask=ask,
    )

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncGenerator[dict[str, object]]:
        async with AsyncExitStack() as stack:
            if gate is not None:
                _ = await stack.enter_async_context(gate)
            try:
                yield {}
            finally:
                await sessions.close()

    server = FastMCP(
        "forbql",
        instructions=instructions(policy, connection=connection, profile=profile),
        lifespan=lifespan,
        mask_error_details=True,
        auth=None
        if gate is None
        else TokenGate(gate, connection=connection, profile=profile),
        middleware=[]
        if gate is None
        else [Capabilities(gate), rate_limit(), OneQueryEach()],
    )
    tokens = gate is not None
    for tool in (tools.search_schema, tools.describe_table, tools.check_sql):
        _ = server.tool(
            tool,
            annotations=_READ_ONLY,
            auth=_needs(NEEDS[tool.__name__], tokens=tokens),
        )
    _ = server.tool(
        tools.run_sql,
        annotations=_READ_ONLY,
        output_schema=None,
        auth=_needs(NEEDS["run_sql"], tokens=tokens),
    )
    _ = server.tool(
        tools.propose_example,
        annotations=_PROPOSING,
        auth=_needs(NEEDS["propose_example"], tokens=tokens),
    )
    reading = _needs(Capability.SCHEMA_READ, tokens=tokens)
    for uri, read in (
        ("forbql://erd", tools.erd),
        ("forbql://erd/{table}", tools.erd_around),
        ("forbql://glossary", tools.glossary),
    ):
        _ = server.resource(uri, mime_type="text/plain", auth=reading)(read)
    return server


def _needs(capability: Capability, *, tokens: bool) -> AuthCheck | None:
    """Hide a tool or resource from a token without the capability it needs.

    Args:
        capability: Capability - What it needs.
        tokens: bool - Whether callers present tokens; without them (stdio) the
            caller is the local user and nothing is hidden.

    Returns:
        AuthCheck | None - The check; None without tokens.

    """
    return require_scopes(capability.value) if tokens else None


async def _read[T](sessions: _Sessions, work: Callable[[Session], Awaitable[T]]) -> T:
    """Read a resource through the session, refusing with the reason.

    Args:
        sessions: _Sessions - The server's session.
        work: Callable[[Session], Awaitable[T]] - The read.

    Returns:
        T - What was read.

    Raises:
        ResourceError: If the session cannot open or refuses the read.

    """
    try:
        return await work(await sessions.get())
    except (SessionError, PolicyError, UnknownProfileError) as err:
        raise ResourceError(str(err)) from err


def _ran(result: RunResult, max_rows: int) -> ToolResult:
    """Say what a run did, with the rows cut to the budget.

    Args:
        result: RunResult - The run.
        max_rows: int - Rows a model receives at most.

    Returns:
        ToolResult - The answer.

    """
    verdict = result.verdict
    if not verdict.allowed:
        return reply(_rejection(verdict))
    if result.error is not None:
        return reply(f"database error ({result.error}): {result.hint}")
    if result.decision is not CostDecision.OK:
        return reply(f"stopped: {result.hint}")
    fitted = fit(result.rows, limited=result.truncated, max_rows=max_rows)
    count = len(fitted.rows)
    summary = f"{count} row" if count == 1 else f"{count} rows"
    if fitted.cut_by is not None:
        summary += (
            f", cut by the {fitted.cut_by} limit: use aggregates for totals, "
            "ORDER BY and LIMIT for samples"
        )
    if fitted.cells_cut:
        summary += "; long values were shortened"
    return reply(
        _allowed(summary, verdict),
        {"columns": list(result.columns), "rows": fitted.rows},
    )


def _allowed(summary: str, verdict: Verdict) -> str:
    """Add what the firewall changed to a summary.

    Args:
        summary: str - The summary.
        verdict: Verdict - The verdict.

    Returns:
        str - The summary, and the firewall's rewrites if any.

    """
    if verdict.rewrites:
        return f"{summary}; the firewall {'; '.join(verdict.rewrites)}"
    return summary


def _rejection(verdict: Verdict) -> str:
    """Say why the firewall refused a query and how to fix it.

    Args:
        verdict: Verdict - The verdict.

    Returns:
        str - One line per violation.

    """
    lines = ["rejected:"]
    for violation in verdict.violations:
        hint = f" ({violation.hint})" if violation.hint else ""
        lines.append(f"- {violation.rule}: {violation.message}{hint}")
    return "\n".join(lines)


def _question(result: RunResult, engine: Engine) -> str:
    """Write what the person reads before an expensive query runs.

    The query is shown as the firewall regenerated it, without comments, so text
    in the query cannot speak to the person.

    Args:
        result: RunResult - The stopped run.
        engine: Engine - The connection's engine.

    Returns:
        str - The question.

    """
    shown = sqlglot.parse_one(result.verdict.sql or "", read=engine.value).sql(
        dialect=engine.value,
        comments=False,
        pretty=True,
    )
    return (
        f"An agent wants to run a query the planner estimates at cost "
        f"{result.cost:,.0f}. Run it?\n\n{shown}"
    )
