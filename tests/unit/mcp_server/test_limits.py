from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools import ToolResult
from mcp.types import CallToolRequestParams

from forbql.mcp import OneQueryEach

if TYPE_CHECKING:
    from fastmcp.server.middleware import CallNext


def call(tool: str) -> MiddlewareContext[CallToolRequestParams]:
    return MiddlewareContext(message=CallToolRequestParams(name=tool, arguments={}))


def after(
    release: asyncio.Event | None = None,
) -> CallNext[CallToolRequestParams, ToolResult]:
    async def rest(context: MiddlewareContext[CallToolRequestParams]) -> ToolResult:
        assert context.message.name
        if release is None:
            await asyncio.sleep(0)
        else:
            _ = await release.wait()
        return ToolResult(content=[])

    return rest


def test_a_second_query_from_one_token_is_refused_while_the_first_runs():
    async def go() -> list[str]:
        release = asyncio.Event()
        limits = OneQueryEach(who=lambda: "token:a")
        first = asyncio.create_task(
            limits.on_call_tool(call("run_sql"), after(release)),
        )
        await asyncio.sleep(0)
        outcomes: list[str] = []
        for tool in ("run_sql", "check_sql"):
            try:
                _ = await limits.on_call_tool(call(tool), after())
                outcomes.append(f"{tool} ran")
            except ToolError as err:
                outcomes.append(f"{tool}: {err}")
        release.set()
        _ = await first
        _ = await limits.on_call_tool(call("run_sql"), after())
        outcomes.append("run_sql ran after")
        return outcomes

    assert asyncio.run(go()) == [
        "run_sql: your previous query is still running; wait for it",
        "check_sql ran",
        "run_sql ran after",
    ]


def test_other_tokens_query_while_one_does():
    async def go() -> None:
        release = asyncio.Event()
        who = ["token:a"]
        limits = OneQueryEach(who=lambda: who[0])
        first = asyncio.create_task(
            limits.on_call_tool(call("run_sql"), after(release)),
        )
        await asyncio.sleep(0)
        who[0] = "token:b"
        _ = await limits.on_call_tool(call("run_sql"), after())
        release.set()
        _ = await first

    asyncio.run(go())


def test_calls_past_the_server_cap_are_refused():
    async def go() -> None:
        release = asyncio.Event()
        limits = OneQueryEach(calls=1, who=lambda: "token:a")
        first = asyncio.create_task(
            limits.on_call_tool(call("search_schema"), after(release)),
        )
        await asyncio.sleep(0)
        try:
            with pytest.raises(ToolError, match="the server is busy"):
                _ = await limits.on_call_tool(call("check_sql"), after())
        finally:
            release.set()
            _ = await first

    asyncio.run(go())
