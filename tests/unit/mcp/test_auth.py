from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools import ToolResult
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.types import CallToolRequestParams

from forbql.access import Capability
from forbql.mcp import Capabilities

if TYPE_CHECKING:
    from collections.abc import Generator

    from fastmcp.server.middleware import CallNext


class _Refusals:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def refuse(self, principal: str, asked: str, reason: str) -> None:
        self.calls.append((principal, asked, reason))


def call(tool: str) -> MiddlewareContext[CallToolRequestParams]:
    return MiddlewareContext(message=CallToolRequestParams(name=tool, arguments={}))


def proceeding() -> tuple[CallNext[CallToolRequestParams, ToolResult], list[str]]:
    seen: list[str] = []

    async def rest(context: MiddlewareContext[CallToolRequestParams]) -> ToolResult:
        await asyncio.sleep(0)
        seen.append(context.message.name)
        return ToolResult(content=[])

    return rest, seen


@contextmanager
def signed_in(client_id: str, *scopes: str) -> Generator[None, None, None]:
    handle = auth_context_var.set(
        AuthenticatedUser(
            AccessToken(token=client_id, client_id=client_id, scopes=[*scopes]),
        ),
    )
    try:
        yield
    finally:
        auth_context_var.reset(handle)


def test_a_missing_token_is_refused_without_recording_it():
    gate = _Refusals()
    capabilities = Capabilities(gate)  # pyright: ignore[reportArgumentType]
    rest, seen = proceeding()

    async def go() -> None:
        with pytest.raises(ToolError) as raised:
            _ = await capabilities.on_call_tool(call("search_schema"), rest)
        assert str(raised.value) == (
            "a token is required to use search_schema: it needs schema.read"
        )

    asyncio.run(go())
    assert seen == []
    assert gate.calls == []


def test_a_token_with_the_capability_may_call():
    gate = _Refusals()
    capabilities = Capabilities(gate)  # pyright: ignore[reportArgumentType]
    rest, seen = proceeding()

    async def go() -> ToolResult:
        with signed_in("token:9", Capability.SCHEMA_READ.value, "bank:analyst"):
            return await capabilities.on_call_tool(call("search_schema"), rest)

    assert asyncio.run(go()) == ToolResult(content=[])
    assert seen == ["search_schema"]
    assert gate.calls == []


def test_a_token_without_the_capability_is_refused():
    gate = _Refusals()
    capabilities = Capabilities(gate)  # pyright: ignore[reportArgumentType]
    rest, seen = proceeding()

    async def go() -> None:
        with (
            signed_in("token:9", Capability.SQL_RUN.value, "bank:analyst"),
            pytest.raises(ToolError) as raised,
        ):
            _ = await capabilities.on_call_tool(call("search_schema"), rest)
        assert str(raised.value) == (
            "this token may not use search_schema: it needs schema.read"
        )

    asyncio.run(go())
    assert seen == []
    assert gate.calls == [("token:9", "search_schema", "needs schema.read")]
