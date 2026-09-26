"""Schema search through a session and the CLI, on the stand.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

import forbql
from forbql import Engine, SessionError
from forbql.cli import app
from forbql.session import sync_schema
from forbql.store import SecretKey, Store
from support.corpus import DEMO
from support.stand import READER
from support.store import STORE_APP, fresh_store

if TYPE_CHECKING:
    from pathlib import Path

    from forbql.knowledge import SearchHit

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("store")]

POLICY = DEMO / "forbql.yaml"
CONNECTION = "bank-postgres"
KEY = SecretKey.generate()
runner = CliRunner()


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FORBQL_STORE_DSN", fresh_store())
    monkeypatch.setenv("FORBQL_SECRET_KEY", KEY)
    monkeypatch.setenv("FORBQL_POLICY", str(POLICY))
    monkeypatch.chdir(tmp_path)

    async def go() -> None:
        async with Store.open(STORE_APP, key=SecretKey.load(KEY, None)) as opened:
            await opened.add_connection(
                CONNECTION,
                Engine.POSTGRES,
                READER[Engine.POSTGRES],
            )
        _ = await sync_schema(POLICY, connection=CONNECTION)

    asyncio.run(go())


def find(question: str) -> list[SearchHit]:
    async def go() -> list[SearchHit]:
        async with forbql.connect(
            POLICY,
            connection=CONNECTION,
            profile="analyst",
        ) as s:
            return await s.search(question)

    return asyncio.run(go())


def test_a_session_finds_tables_and_brings_the_joined_ones():
    hits = find("currency")

    assert hits[0].table == "public.accounts"
    assert "public.clients" in [hit.table for hit in hits]


def test_search_shows_only_what_the_profile_sees():
    hits = find("passport secrets api key canary")

    tables = {hit.table for hit in hits}
    assert "public.secrets" not in tables
    assert "public.canary" not in tables
    assert "passport" not in [c for hit in hits for c in hit.columns]


def test_without_a_store_there_is_no_search(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("FORBQL_STORE_DSN")

    async def go() -> None:
        async with forbql.connect(
            POLICY,
            connection=CONNECTION,
            profile="analyst",
            dsn=READER[Engine.POSTGRES],
        ) as session:
            _ = await session.search("balance")

    with pytest.raises(SessionError, match="schema search needs the store"):
        asyncio.run(go())


def test_the_cli_searches_and_reindexes():
    found = runner.invoke(
        app,
        [
            "knowledge",
            "search",
            "currency",
            "--connection",
            CONNECTION,
            "--profile",
            "analyst",
        ],
    )
    rebuilt = runner.invoke(app, ["knowledge", "reindex", CONNECTION])

    assert found.exit_code == 0, found.stderr
    assert found.stdout.splitlines()[0].startswith("public.accounts (")
    assert rebuilt.exit_code == 0
    assert rebuilt.stdout.startswith(f"{CONNECTION}: ")
    assert rebuilt.stdout.endswith(" embedded, 0 removed\n")
