"""`forbql mcp --http` as an operator starts it: a process on a port, with tokens.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess  # ruff: ignore[suspicious-subprocess-import] - runs forbql itself
from typing import TYPE_CHECKING

import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from mcp.types import TextContent

from forbql import Engine
from forbql.session import sync_schema
from forbql.store import SecretKey, Store
from support.corpus import DEMO
from support.stand import READER
from support.store import STORE_APP, fresh_store
from support.tokens import issue

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

KEY = SecretKey.generate()


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def wait_for(port: int) -> None:
    for _ in range(100):
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            await asyncio.sleep(0.1)
        else:
            writer.close()
            return
    msg = f"nothing listens on {port}"
    raise TimeoutError(msg)


def test_the_command_serves_tokens_over_http_and_never_prints_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    dsn = fresh_store()
    monkeypatch.setenv("FORBQL_STORE_DSN", dsn)
    monkeypatch.setenv("FORBQL_SECRET_KEY", KEY)

    async def prepare() -> None:
        async with Store.open(STORE_APP, key=SecretKey.load(KEY, None)) as opened:
            await opened.add_connection(
                "bank-postgres",
                Engine.POSTGRES,
                READER[Engine.POSTGRES],
            )
        _ = await sync_schema(DEMO / "forbql.yaml", connection="bank-postgres")

    asyncio.run(prepare())
    token = issue("agent", "bank-postgres:analyst:sql.run")
    command = shutil.which("forbql")
    assert command is not None
    port = free_port()
    output = tmp_path / "output.log"
    environment = {k: v for k, v in os.environ.items() if not k.startswith("FORBQL_")}
    environment |= {"FORBQL_STORE_DSN": dsn, "FORBQL_SECRET_KEY": KEY}
    with output.open("wb") as log:
        server = subprocess.Popen(  # ruff: ignore[subprocess-without-shell-equals-true] - our own command, fixed arguments
            [
                command,
                "mcp",
                "--policy",
                str(DEMO / "forbql.yaml"),
                "--connection",
                "bank-postgres",
                "--profile",
                "analyst",
                "--http",
                "--port",
                str(port),
            ],
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:

            async def go() -> str:
                await wait_for(port)
                transport = StreamableHttpTransport(
                    f"http://127.0.0.1:{port}/mcp",
                    headers={"Authorization": f"Bearer {token.value}"},
                )
                async with Client(transport) as client:
                    ran = await client.call_tool("run_sql", {"sql": "SELECT 1 AS one"})
                    [content] = ran.content
                    assert isinstance(content, TextContent)
                    return content.text

            answer = asyncio.run(go())
        finally:
            server.terminate()
            _ = server.wait(timeout=10)

    assert answer.startswith("1 row;")
    printed = output.read_text(encoding="utf-8", errors="replace")
    assert token.value not in printed
    assert token.value.rsplit("_", 1)[1] not in printed
