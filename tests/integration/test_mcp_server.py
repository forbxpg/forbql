"""The MCP server over an in-memory client, on the stand.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
import json
from functools import partial
from typing import TYPE_CHECKING

import pytest
from fastmcp import Client
from fastmcp.client.elicitation import ElicitResult
from mcp.shared.exceptions import MCPError
from mcp.types import TextContent

import forbql
from forbql import Engine
from forbql.mcp import build_server
from forbql.policy import load_policy, parse_policy
from forbql.session import sync_knowledge, sync_schema
from forbql.store import SecretKey, Store
from support.corpus import DEMO
from support.stand import READER
from support.store import STORE_APP, fresh_store

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from fastmcp.client.client import CallToolResult
    from fastmcp.client.transports import FastMCPTransport

    from forbql.policy import Policy

    type McpClient = Client[FastMCPTransport]

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("store")]

CONNECTION = "bank-postgres"
KEY = SecretKey.generate()
POLICY = load_policy(DEMO / "forbql.yaml")
# The analyst of the demo policy, with every query expensive enough to ask about.
EXPENSIVE = parse_policy(
    (DEMO / "forbql.yaml")
    .read_text(encoding="utf-8")
    .replace(
        "      analyst:\n        tables:\n",
        """      analyst:
        explain: { confirm_cost: 1, block_cost: 1.0e15 }
        tables:
""",
        1,
    ),
)


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORBQL_STORE_DSN", fresh_store())
    monkeypatch.setenv("FORBQL_SECRET_KEY", KEY)

    async def go() -> None:
        async with Store.open(STORE_APP, key=SecretKey.load(KEY, None)) as opened:
            await opened.add_connection(
                CONNECTION,
                Engine.POSTGRES,
                READER[Engine.POSTGRES],
            )
        _ = await sync_schema(POLICY, connection=CONNECTION)
        _ = await sync_knowledge(
            POLICY,
            connection=CONNECTION,
            path=DEMO / "knowledge.yaml",
        )

    asyncio.run(go())


def served[T](
    tmp_path: Path,
    work: Callable[[McpClient], Awaitable[T]],
    *,
    policy: Policy = POLICY,
    answer: bool | None = None,
    mode: str = "auto",
) -> T:
    server = build_server(
        policy,
        connection=CONNECTION,
        profile="analyst",
        opener=partial(
            forbql.connect,
            policy,
            connection=CONNECTION,
            profile="analyst",
            audit_log=tmp_path / "audit.jsonl",
            principal="local:tester",
        ),
    )

    async def handler(
        _message: str,
        _type: object,
        params: object,
        _ctx: object,
    ) -> object:
        await asyncio.sleep(0)
        if not answer:
            return ElicitResult(action="decline")
        # 2026-07-28 asks for {"run": bool}; before it, a bool travels as {"value"}.
        asked = getattr(params, "requested_schema", {}).get("properties", {})
        return {"value": True} if "value" in asked else {"run": True}

    async def go() -> T:
        async with Client(
            server,
            elicitation_handler=handler if answer is not None else None,
            mode=mode,
        ) as client:
            return await work(client)

    return asyncio.run(go())


def call(tmp_path: Path, tool: str, **arguments: object) -> CallToolResult:
    return served(
        tmp_path,
        lambda client: client.call_tool(tool, arguments, raise_on_error=False),
    )


def text(result: CallToolResult) -> str:
    [content] = result.content
    assert isinstance(content, TextContent)
    return content.text


def records(tmp_path: Path) -> list[dict[str, object]]:
    lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_four_read_only_tools_and_profile_instructions(tmp_path: Path):
    async def work(client: McpClient) -> tuple[list[str], list[bool | None], str]:
        tools = await client.list_tools()
        return (
            sorted(t.name for t in tools),
            [t.annotations.read_only_hint if t.annotations else None for t in tools],
            client.instructions or "",
        )

    names, read_only, instructions = served(tmp_path, work)

    assert names == ["check_sql", "describe_table", "run_sql", "search_schema"]
    assert read_only == [True] * 4
    assert 'the profile "analyst"' in instructions


def test_search_answers_with_tables_and_knowledge_as_data(tmp_path: Path):
    found = call(tmp_path, "search_schema", query="деньги на счетах")

    assert not found.is_error
    assert text(found).split("\n")[0].endswith("examples")
    assert "\n<untrusted-data nonce=" in text(found)
    data = found.structured_content or {}
    assert "public.accounts" in [t["table"] for t in data["tables"]]
    assert data["glossary"]
    assert records(tmp_path)[0]["principal"] == "local:tester"


def test_describe_refuses_a_hidden_table_as_it_would_a_missing_one(tmp_path: Path):
    hidden = call(tmp_path, "describe_table", table="public.secrets")
    missing = call(tmp_path, "describe_table", table="public.nothing")

    assert hidden.is_error
    assert text(hidden).replace("secrets", "x") == text(missing).replace("nothing", "x")


def test_a_rejection_is_an_answer_with_the_reason(tmp_path: Path):
    rejected = call(tmp_path, "check_sql", sql="SELECT passport FROM clients")
    allowed = call(tmp_path, "check_sql", sql="SELECT count(*) FROM accounts")

    assert not rejected.is_error
    assert text(rejected).startswith("rejected:\n- ")
    assert (allowed.structured_content or {})["sql"].startswith("SELECT")


def test_rows_come_within_the_budget_and_the_cut_is_named(tmp_path: Path):
    ran = call(tmp_path, "run_sql", sql="SELECT id, amount FROM transactions")

    summary = text(ran).split("\n")[0]
    assert summary.startswith("200 rows, cut by the rows limit")
    assert len((ran.structured_content or {})["rows"]) == 200


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize(("answer", "rows"), [(True, True), (False, False)])
def test_an_expensive_query_runs_only_if_the_person_says_yes(
    tmp_path: Path,
    mode: str,
    *,
    answer: bool,
    rows: bool,
):
    ran = served(
        tmp_path,
        lambda client: client.call_tool(
            "run_sql",
            {"sql": "SELECT count(*) FROM transactions"},
            raise_on_error=False,
        ),
        policy=EXPENSIVE,
        answer=answer,
        mode=mode,
    )

    assert text(ran).startswith("1 row;") is rows
    assert text(ran).startswith("stopped: the person") is not rows


def test_the_server_explains_why_it_is_not_ready_and_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("FORBQL_STORE_DSN")

    async def work(client: McpClient) -> tuple[CallToolResult, CallToolResult]:
        before = await client.call_tool(
            "run_sql",
            {"sql": "SELECT 1 AS one"},
            raise_on_error=False,
        )
        monkeypatch.setenv("FORBQL_DSN_BANK_POSTGRES", READER[Engine.POSTGRES])
        after = await client.call_tool(
            "run_sql",
            {"sql": "SELECT 1 AS one"},
            raise_on_error=False,
        )
        return before, after

    before, after = served(tmp_path, work)

    assert before.is_error
    assert text(before).startswith("forbql is not ready: ")
    assert text(after).startswith("1 row;")


def test_resources_draw_the_schema_and_list_the_glossary(tmp_path: Path):
    async def work(client: McpClient) -> tuple[str, str, str]:
        drawn = await client.read_resource("forbql://erd")
        around = await client.read_resource("forbql://erd/transactions")
        glossary = await client.read_resource("forbql://glossary")
        return (
            getattr(drawn[0], "text", ""),
            getattr(around[0], "text", ""),
            getattr(glossary[0], "text", ""),
        )

    drawn, around, glossary = served(tmp_path, work)

    assert drawn.startswith("erDiagram")
    assert "public_transactions" in around
    assert glossary.startswith("<untrusted-data nonce=")
    assert '"term": "открытый счёт"' in glossary
    assert [r["action"] for r in records(tmp_path)] == ["resource.read"] * 3


def test_a_hidden_table_has_no_diagram(tmp_path: Path):
    async def work(client: McpClient) -> str:
        with pytest.raises(MCPError) as refused:
            _ = await client.read_resource("forbql://erd/secrets")
        return str(refused.value)

    assert "table secrets is not available" in served(tmp_path, work)
