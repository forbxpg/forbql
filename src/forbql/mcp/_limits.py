"""Limits per token over HTTP: requests per second, and one query at a time.

The database connection behind a session runs one query at a time, so a token
with a slow query would hold every other token behind it; a second query from the
same token is refused at once instead, and so is any call past the server's cap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware
from fastmcp.server.middleware.rate_limiting import RateLimitingMiddleware

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastmcp.server.middleware import CallNext, MiddlewareContext
    from fastmcp.tools import ToolResult
    from mcp.types import CallToolRequestParams

PER_SECOND = 10.0
"""Requests a token may make per second, sustained."""

BURST = 20
"""Requests a token may make at once before the rate applies."""

CALLS = 16
"""Tool calls the server runs at once, across every token."""


def caller() -> str:
    """Name the token behind this request.

    Returns:
        str - `token:<id>`; `local` without a token.

    """
    token = get_access_token()
    return "local" if token is None else token.client_id


def rate_limit() -> RateLimitingMiddleware:
    """Limit each token's requests per second.

    Returns:
        RateLimitingMiddleware - FastMCP's limiter, keyed by token.

    """
    return RateLimitingMiddleware(
        max_requests_per_second=PER_SECOND,
        burst_capacity=BURST,
        get_client_id=lambda _context: caller(),
    )


class OneQueryEach(Middleware):
    """Refuses a token's second query while its first runs, and calls past the cap.

    Args:
        calls: int - Tool calls to run at once, across every token.
        who: Callable[[], str] - Names the caller of the current request.

    """

    _calls: int
    _who: Callable[[], str]
    _running: int
    _querying: set[str]

    def __init__(self, calls: int = CALLS, who: Callable[[], str] = caller) -> None:
        self._calls = calls
        self._who = who
        self._running = 0
        self._querying = set()

    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        """Run a call if the caller and the server have room for it.

        Args:
            context: MiddlewareContext[CallToolRequestParams] - The call.
            call_next: CallNext[CallToolRequestParams, ToolResult] - The rest.

        Returns:
            ToolResult - The tool's result.

        Raises:
            ToolError: If the server runs as many calls as it may, or the caller's
                query is still running.

        """
        who = self._who()
        query = context.message.name == "run_sql"
        if self._running >= self._calls:
            msg = "the server is busy; try again in a moment"
            raise ToolError(msg)
        if query and who in self._querying:
            msg = "your previous query is still running; wait for it"
            raise ToolError(msg)
        self._running += 1
        if query:
            self._querying.add(who)
        try:
            return await call_next(context)
        finally:
            self._running -= 1
            if query:
                self._querying.discard(who)
