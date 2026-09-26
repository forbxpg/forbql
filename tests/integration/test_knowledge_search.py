"""Glossary terms and examples in search, per profile, on the stand.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

import forbql
from forbql import Engine
from forbql.cli import app
from forbql.session import sync_knowledge, sync_schema
from forbql.store import SecretKey, Store
from support.knowledge import LIVE_KNOWLEDGE, LIVE_POLICY
from support.stand import READER
from support.store import STORE_APP, fresh_store

if TYPE_CHECKING:
    from pathlib import Path

    from forbql.knowledge import SearchResult

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("loaded")]

CONNECTION = "bank-postgres"
KEY = SecretKey.generate()
runner = CliRunner()


@pytest.fixture
def loaded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    policy = tmp_path / "forbql.yaml"
    _ = policy.write_text(LIVE_POLICY, encoding="utf-8")
    knowledge = tmp_path / "knowledge.yaml"
    _ = knowledge.write_text(LIVE_KNOWLEDGE, encoding="utf-8")
    monkeypatch.setenv("FORBQL_STORE_DSN", fresh_store())
    monkeypatch.setenv("FORBQL_SECRET_KEY", KEY)
    monkeypatch.setenv("FORBQL_POLICY", str(policy))

    async def go() -> None:
        async with Store.open(STORE_APP, key=SecretKey.load(KEY, None)) as opened:
            await opened.add_connection(
                CONNECTION,
                Engine.POSTGRES,
                READER[Engine.POSTGRES],
            )
        _ = await sync_schema(policy, connection=CONNECTION)
        _ = await sync_knowledge(policy, connection=CONNECTION, path=knowledge)

    asyncio.run(go())
    return policy


def find(policy: Path, profile: str, question: str) -> SearchResult:
    async def go() -> SearchResult:
        async with forbql.connect(
            policy,
            connection=CONNECTION,
            profile=profile,
        ) as session:
            return await session.search(question)

    return asyncio.run(go())


def test_a_profile_finds_the_terms_and_examples_it_may_see(loaded: Path):
    found = find(loaded, "analyst", "deposits per region of open accounts")

    assert "open account" in [t.term for t in found.glossary]
    assert "Deposits per region" in [e.question for e in found.examples]
    assert found.tables


def test_another_profile_finds_only_its_own(loaded: Path):
    found = find(loaded, "teller", "deposits per region of open accounts")

    assert [t.term for t in found.glossary] == ["fiscal year"]
    assert [e.question for e in found.examples] == ["Money on accounts per currency"]


def test_the_cli_shows_terms_and_examples():
    found = runner.invoke(
        app,
        [
            "knowledge",
            "search",
            "open accounts",
            "--connection",
            CONNECTION,
            "--profile",
            "analyst",
        ],
    )

    assert found.exit_code == 0, found.stderr
    assert (
        "glossary: open account: An account still in use."
        "  [public.accounts: status = 'open']"
    ) in found.stdout.splitlines()
    assert "example: Money on accounts per currency" in found.stdout.splitlines()
