"""The MCP server over HTTP with tokens, in process, on the stand.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
import hashlib
from functools import partial
from typing import TYPE_CHECKING, cast

import pytest
from fastmcp.utilities.tests import asgi_server
from mcp.shared.exceptions import MCPError

import forbql
from forbql import Engine
from forbql.mcp import BURST, app_options, build_server, listening
from forbql.policy import load_policy, parse_policy
from forbql.session import Gate, sync_schema
from forbql.store import SecretKey, Store
from support.corpus import DEMO
from support.stand import READER
from support.store import STORE_APP, fresh_store
from support.tokens import audited, issue, revoke

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport
    from fastmcp.utilities.tests import ASGIServer

    from forbql.policy import Policy


pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("store")]

CONNECTION = "bank-postgres"
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
KEY = SecretKey.generate()
EVERYTHING = f"{CONNECTION}:analyst:schema.read,sql.check,sql.run"
HELLO = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
}


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

    asyncio.run(go())


def over_http[T](
    work: Callable[[ASGIServer], Awaitable[T]],
    *,
    policy: Policy = POLICY,
    ask: bool = False,
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
        ),
        gate=Gate(policy, connection=CONNECTION, profile="analyst"),
        ask=ask,
    )

    async def go() -> T:
        async with asgi_server(server, **app_options(listening("127.0.0.1"))) as served:  # pyright: ignore[reportArgumentType]
            return await work(served)

    return asyncio.run(go())


def bearer(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}"}


def calling(served: ASGIServer, token: str) -> Client[StreamableHttpTransport]:
    connected = served.client(headers=bearer(token))  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    return cast("Client[StreamableHttpTransport]", connected)


def status(headers: dict[str, str]) -> tuple[int, str]:
    async def work(served: ASGIServer) -> tuple[int, str]:
        async with served.http_client(headers=headers) as http:
            answer = await http.post(
                served.url,
                json=HELLO,
                headers={"Accept": "application/json, text/event-stream"},
            )
            return answer.status_code, answer.text

    return over_http(work)


def test_without_a_token_or_with_a_revoked_one_the_answer_is_401():
    token = issue("agent", EVERYTHING)
    revoke(token.token_id)

    assert status({})[0] == 401
    assert status(bearer("garbage"))[0] == 401
    assert status(bearer(token.value))[0] == 401
    assert audited() == [
        (f"token:{token.token_id}", "access.denied", "authenticate", "revoked"),
    ]


def test_a_token_granted_elsewhere_is_told_so_with_403():
    token = issue("elsewhere", "bank-mysql:analyst:sql.run")

    code, body = status(bearer(token.value))

    assert code == 403
    assert f"{CONNECTION}:analyst" in body
    assert audited()[-1][1:] == ("access.denied", "authenticate", "no grant")


def test_tools_a_token_may_not_use_are_hidden_and_refused():
    token = issue("reader", f"{CONNECTION}:analyst:schema.read")

    async def work(served: ASGIServer) -> tuple[list[str], bool, str]:
        async with calling(served, token.value) as client:
            names = sorted(tool.name for tool in await client.list_tools())
            refused = await client.call_tool(
                "run_sql",
                {"sql": "SELECT 1 AS one"},
                raise_on_error=False,
            )
            return names, refused.is_error, str(refused.content)

    names, is_error, text = over_http(work)

    assert names == ["describe_table", "search_schema"]
    assert is_error
    assert "sql.run" in text
    assert (
        f"token:{token.token_id}",
        "access.denied",
        "run_sql",
        "needs sql.run",
    ) in audited()


def test_a_token_proposes_as_its_author_only_with_the_capability():
    token = issue("agent", f"{EVERYTHING},knowledge.propose")
    sql = "SELECT status, count(*) FROM accounts GROUP BY status"

    async def work(served: ASGIServer) -> tuple[list[str], bool]:
        async with calling(served, token.value) as client:
            names = [tool.name for tool in await client.list_tools()]
            proposed = await client.call_tool(
                "propose_example",
                {"question": "Accounts per status", "sql": sql},
            )
            return names, proposed.is_error

    names, is_error = over_http(work)

    assert "propose_example" in names
    assert not is_error
    assert audited()[-1] == (
        f"token:{token.token_id}",
        "knowledge.propose",
        sql,
        None,
    )
    assert proposal_authors() == [f"token:{token.token_id}"]


def proposal_authors() -> list[str]:
    async def go() -> list[str]:
        async with Store.open(STORE_APP) as store:
            return [p.author for p in await store.proposals.listed()]

    return asyncio.run(go())


def test_each_call_is_recorded_under_the_token_that_made_it():
    token = issue("agent", EVERYTHING)

    async def work(served: ASGIServer) -> bool:
        async with calling(served, token.value) as client:
            ran = await client.call_tool("run_sql", {"sql": "SELECT 1 AS one"})
            return ran.is_error

    assert over_http(work) is False
    assert audited()[-1][:2] == (f"token:{token.token_id}", "sql.run")


def test_a_token_revoked_between_calls_is_refused_at_once():
    token = issue("agent", EVERYTHING)

    async def work(served: ASGIServer) -> tuple[bool, int]:
        async with calling(served, token.value) as client:
            first = await client.call_tool("check_sql", {"sql": "SELECT 1 AS one"})
        async with Store.open(STORE_APP) as store:
            _ = await store.tokens.revoke(token.token_id)
        async with served.http_client(headers=bearer(token.value)) as http:
            again = await http.post(
                served.url,
                json=HELLO,
                headers={"Accept": "application/json, text/event-stream"},
            )
        return first.is_error, again.status_code

    assert over_http(work) == (False, 401)


def test_a_token_that_calls_too_fast_is_slowed_down():
    token = issue("agent", EVERYTHING)

    async def work(served: ASGIServer) -> list[str]:
        refused: list[str] = []
        async with calling(served, token.value) as client:
            for _ in range(BURST + 10):
                try:
                    _ = await client.list_tools()
                except MCPError as err:
                    refused.append(str(err))
        return refused

    refused = over_http(work)

    assert refused
    assert all("Rate limit exceeded" in reason for reason in refused)


@pytest.mark.parametrize(
    ("header", "value", "code"),
    [("Host", "evil.example.com", 421), ("Origin", "http://evil.example.com", 403)],
)
def test_a_request_from_elsewhere_is_refused_before_the_token_is_read(
    header: str,
    value: str,
    code: int,
):
    token = issue("agent", EVERYTHING)

    assert status({**bearer(token.value), header: value})[0] == code


@pytest.mark.parametrize(("ask", "answer"), [(False, "stopped:"), (True, "1 row;")])
def test_over_http_an_expensive_query_is_stopped_unless_the_server_asks(
    ask: bool,  # ruff: ignore[boolean-type-hint-positional-argument] - a parameter of the test
    answer: str,
):
    token = issue("agent", EVERYTHING)

    async def work(served: ASGIServer) -> str:
        async def yes(*_: object) -> dict[str, bool]:
            await asyncio.sleep(0)
            return {"run": True}

        connected = served.client(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            headers=bearer(token.value),
            elicitation_handler=yes,
        )
        async with cast("Client[StreamableHttpTransport]", connected) as client:
            ran = await client.call_tool(
                "run_sql",
                {"sql": "SELECT count(*) FROM transactions"},
            )
            return str(ran.content)

    assert answer in over_http(work, policy=EXPENSIVE, ask=ask)


@pytest.mark.parametrize("state", ["digest", "v1.forged"])
def test_a_forged_answer_to_the_question_runs_nothing(state: str):
    token = issue("agent", EVERYTHING)
    sql = "SELECT count(*) FROM transactions"
    forged = (
        hashlib.sha256(f"{sql} LIMIT 1000".encode()).hexdigest()
        if state == "digest"
        else state
    )

    async def work(served: ASGIServer) -> str:
        async with served.http_client(headers=bearer(token.value)) as http:
            answer = await http.post(
                served.url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "run_sql",
                        "arguments": {"sql": sql},
                        "inputResponses": {
                            "confirm": {"action": "accept", "content": {"run": True}},
                        },
                        "requestState": forged,
                        "_meta": {
                            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                        },
                    },
                },
                headers={
                    "Accept": "application/json, text/event-stream",
                    "MCP-Protocol-Version": "2026-07-28",
                    "Mcp-Method": "tools/call",
                    "Mcp-Name": "run_sql",
                },
            )
            return answer.text

    answered = over_http(work, policy=EXPENSIVE, ask=True)

    assert '"rows"' not in answered
    assert not [row for row in audited() if row[1] == "sql.run" and row[3] is None]
