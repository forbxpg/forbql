"""`forbql mcp` as a client starts it: a process speaking MCP on stdin and stdout.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from typing import TYPE_CHECKING

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from mcp.types import TextContent

from forbql import Engine
from support.corpus import DEMO
from support.stand import READER

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration


def test_the_command_serves_the_profile_over_stdio(tmp_path: Path):
    command = shutil.which("forbql")
    assert command is not None
    log = tmp_path / "audit.jsonl"
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("FORBQL_")
    }
    environment["FORBQL_DSN_BANK_POSTGRES"] = READER[Engine.POSTGRES]
    transport = StdioTransport(
        command=command,
        args=[
            "mcp",
            "--policy",
            str(DEMO / "forbql.yaml"),
            "--connection",
            "bank-postgres",
            "--profile",
            "analyst",
            "--audit-log",
            str(log),
        ],
        env=environment,
    )

    async def go() -> tuple[str, str]:
        async with Client(transport) as client:
            ran = await client.call_tool("run_sql", {"sql": "SELECT 1 AS one"})
            [content] = ran.content
            assert isinstance(content, TextContent)
            return content.text, client.instructions or ""

    answer, instructions = asyncio.run(go())

    assert answer.startswith("1 row; the firewall added LIMIT")
    assert "\n<untrusted-data nonce=" in answer
    assert "bank-postgres" in instructions
    [record] = [
        json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()
    ]
    assert record["principal"].startswith("local:")
