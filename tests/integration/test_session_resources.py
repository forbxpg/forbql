"""The diagram and the glossary through a session, on the stand.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

import forbql
from forbql import Engine, SessionError
from forbql.session import sync_knowledge, sync_schema
from forbql.store import SecretKey, Store
from support.corpus import DEMO
from support.stand import READER
from support.store import STORE_APP, fresh_store

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from forbql import Session

pytestmark = pytest.mark.integration

POLICY = DEMO / "forbql.yaml"
CONNECTION = "bank-postgres"
KEY = SecretKey.generate()


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


def within[T](tmp_path: Path, work: Callable[[Session], Awaitable[T]]) -> T:
    async def go() -> T:
        async with forbql.connect(
            POLICY,
            connection=CONNECTION,
            profile="analyst",
            dsn=READER[Engine.POSTGRES],
            audit_log=tmp_path / "audit.jsonl",
        ) as session:
            return await work(session)

    return asyncio.run(go())


def records(tmp_path: Path) -> list[dict[str, object]]:
    text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def test_the_diagram_shows_what_the_profile_sees(tmp_path: Path):
    drawn = within(tmp_path, lambda session: session.erd())

    assert drawn.startswith("erDiagram")
    assert "public_accounts" in drawn
    assert "passport" not in drawn
    assert "secrets" not in drawn
    assert records(tmp_path)[0]["action"] == "resource.read"


def test_a_diagram_centres_on_a_table(tmp_path: Path):
    drawn = within(tmp_path, lambda session: session.erd("transactions"))

    assert "public_transactions" in drawn
    assert "public_accounts" in drawn
    assert records(tmp_path)[0]["sql"] == "erd transactions"


def test_a_hidden_table_and_a_missing_one_answer_alike(tmp_path: Path):
    messages: list[str] = []
    for table in ("public.secrets", "public.nothing"):
        with pytest.raises(SessionError) as refused:
            _ = within(tmp_path, lambda session, t=table: session.erd(t))
        messages.append(str(refused.value).replace(table, "<table>"))

    assert messages == ["table <table> is not available"] * 2


def test_too_many_tables_are_named_rather_than_drawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr("forbql.session._session.MAX_TABLES", 2)

    listed = within(tmp_path, lambda session: session.erd())

    assert "public.accounts" in listed.splitlines()
    assert "erDiagram" not in listed


@pytest.mark.usefixtures("store")
def test_the_glossary_holds_the_terms_the_profile_may_see(tmp_path: Path):
    terms = within(tmp_path, lambda session: session.glossary())

    assert [t.term for t in terms] == sorted(t.term for t in terms)
    assert "открытый счёт" in [t.term for t in terms]
    assert records(tmp_path)[0]["rows"] == len(terms)


def test_without_a_store_there_is_no_glossary(tmp_path: Path):
    with pytest.raises(SessionError, match="the glossary lives in the store"):
        _ = within(tmp_path, lambda session: session.glossary())

    assert records(tmp_path)[0]["error_class"] == "no_store"
