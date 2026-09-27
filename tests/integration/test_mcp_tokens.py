"""The MCP server over HTTP with tokens, in process, on the stand.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
from functools import partial
from typing import TYPE_CHECKING, cast

import pytest
from fastmcp.utilities.tests import asgi_server

import forbql
from forbql import Engine
from forbql.mcp import build_server
from forbql.policy import load_policy
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

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("store")]

CONNECTION = "bank-postgres"
POLICY = load_policy(DEMO / "forbql.yaml")
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


def over_http[T](work: Callable[[ASGIServer], Awaitable[T]]) -> T:
    server = build_server(
        POLICY,
        connection=CONNECTION,
        profile="analyst",
        opener=partial(
            forbql.connect,
            POLICY,
            connection=CONNECTION,
            profile="analyst",
        ),
        gate=Gate(POLICY, connection=CONNECTION, profile="analyst"),
    )

    async def go() -> T:
        async with asgi_server(server, stateless_http=True) as served:
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
