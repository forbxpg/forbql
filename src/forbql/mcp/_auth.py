"""Tokens over HTTP: who may call, and which tools each capability opens."""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware

from forbql.access import Capability

if TYPE_CHECKING:
    from fastmcp.resources import ResourceResult
    from fastmcp.server.middleware import CallNext, MiddlewareContext
    from fastmcp.tools import ToolResult
    from mcp.types import CallToolRequestParams, ReadResourceRequestParams

    from forbql.session import Gate

NEEDS: dict[str, Capability] = {
    "search_schema": Capability.SCHEMA_READ,
    "describe_table": Capability.SCHEMA_READ,
    "check_sql": Capability.SQL_CHECK,
    "run_sql": Capability.SQL_RUN,
}
"""What each tool needs; every resource needs `schema.read`."""


class TokenGate(TokenVerifier):
    """Checks each request's bearer token with the store; nothing is cached.

    A token let in carries its capabilities here as scopes, and the pair
    `connection:profile` when it has any: without it the request is refused with 403
    and a reason, since the token is valid but granted elsewhere.

    Args:
        gate: Gate - Lets tokens in and audits refusals.
        connection: str - Connection name.
        profile: str - Profile name.

    """

    _gate: Gate
    _pair: str

    def __init__(self, gate: Gate, *, connection: str, profile: str) -> None:
        pair = f"{connection}:{profile}"
        super().__init__(required_scopes=[pair])
        self._gate = gate
        self._pair = pair

    @override
    async def verify_token(self, token: str) -> AccessToken | None:
        """Let a token in, or not.

        Args:
            token: str - The bearer token.

        Returns:
            AccessToken | None - Who it is and its scopes here; None for 401. The
                token itself is not kept, so it cannot reach a log.

        """
        admitted = await self._gate.admit(token)
        if admitted is None:
            return None
        scopes = sorted(capability.value for capability in admitted.capabilities)
        return AccessToken(
            token=admitted.principal,
            client_id=admitted.principal,
            scopes=[*scopes, self._pair] if scopes else [],
        )


class Capabilities(Middleware):
    """Refuses, and audits, a call a token's capabilities do not open.

    Listing already hides such tools; this stops a caller that names one anyway.

    Args:
        gate: Gate - Records the refusal.

    """

    _gate: Gate

    def __init__(self, gate: Gate) -> None:
        self._gate = gate

    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        """Let a tool call through only with the capability it needs.

        Args:
            context: MiddlewareContext[CallToolRequestParams] - The call.
            call_next: CallNext[CallToolRequestParams, ToolResult] - The rest.

        Returns:
            ToolResult - The tool's result.

        """
        name = context.message.name
        await self._require(NEEDS.get(name, Capability.SCHEMA_READ), name)
        return await call_next(context)

    @override
    async def on_read_resource(
        self,
        context: MiddlewareContext[ReadResourceRequestParams],
        call_next: CallNext[ReadResourceRequestParams, ResourceResult],
    ) -> ResourceResult:
        """Let a resource read through only with `schema.read`.

        Args:
            context: MiddlewareContext[ReadResourceRequestParams] - The read.
            call_next: CallNext[ReadResourceRequestParams, ResourceResult] - The rest.

        Returns:
            ResourceResult - The resource.

        """
        await self._require(Capability.SCHEMA_READ, str(context.message.uri))
        return await call_next(context)

    async def _require(self, needed: Capability, asked: str) -> None:
        """Refuse a call whose token lacks a capability, recording the refusal.

        Args:
            needed: Capability - What the call needs.
            asked: str - The tool or resource.

        Raises:
            ToolError: If the token lacks it.

        """
        token = get_access_token()
        if token is None or needed.value in token.scopes:
            return
        await self._gate.refuse(token.client_id, asked, f"needs {needed}")
        msg = f"this token may not use {asked}: it needs {needed}"
        raise ToolError(msg)
