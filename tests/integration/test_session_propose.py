"""Proposing examples through a session, on the stand.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

import forbql
from forbql import Engine, SessionError
from forbql.audit import Action
from forbql.session import QUESTION_CHARS, WAITING, sync_schema
from forbql.store import SecretKey, Store
from support.corpus import DEMO
from support.stand import READER
from support.store import STORE_APP, fresh_store, store_sql

if TYPE_CHECKING:
    from pathlib import Path

    from forbql.store import StoredProposal

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("store")]

POLICY = DEMO / "forbql.yaml"
CONNECTION = "bank-postgres"
KEY = SecretKey.generate()
AGENT = "token:0123456789ab"
QUESTION = "Money on accounts per currency"
SQL = "SELECT currency, sum(balance) FROM accounts GROUP BY currency"


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


def propose(question: str = QUESTION, sql: str = SQL, *, times: int = 1) -> int:
    async def go() -> int:
        async with forbql.connect(
            POLICY,
            connection=CONNECTION,
            profile="analyst",
            principal=AGENT,
        ) as session:
            numbers = [
                await session.propose(f"{question} {n}" if times > 1 else question, sql)
                for n in range(times)
            ]
            return numbers[-1]

    return asyncio.run(go())


def waiting() -> list[StoredProposal]:
    async def go() -> list[StoredProposal]:
        async with Store.open(STORE_APP) as store:
            return await store.proposals.listed()

    return asyncio.run(go())


def audited() -> list[tuple[object, ...]]:
    columns = "principal, profile, allowed, error_class, sql"
    where = f"action = '{Action.KNOWLEDGE_PROPOSE}'"
    query = f"SELECT {columns} FROM forbql.audit_records WHERE {where} ORDER BY seq"
    [rows] = store_sql(STORE_APP, query)
    return rows


def test_a_proposal_waits_under_the_callers_name_and_profile():
    number = propose()

    [found] = waiting()
    assert (found.id, found.author, found.profile) == (number, AGENT, "analyst")
    assert audited() == [(AGENT, "analyst", True, None, SQL)]


@pytest.mark.parametrize(
    ("question", "sql"),
    [
        ("Which client_fingerprints repeat", "SELECT count(*) FROM accounts"),
        (QUESTION, "SELECT count(*) FROM client_fingerprints"),
    ],
)
def test_a_name_the_profile_does_not_see_is_refused_unnamed(question: str, sql: str):
    with pytest.raises(SessionError) as refused:
        _ = propose(question, sql)

    assert str(refused.value) == (
        "it names a table or column this profile does not see"
    )
    assert waiting() == []
    assert audited() == [(AGENT, "analyst", False, "hidden", sql)]


def test_a_query_the_firewall_refuses_is_refused_with_its_reasons():
    with pytest.raises(SessionError, match="the firewall refuses the query: "):
        _ = propose(sql="DELETE FROM accounts")

    assert audited()[0][2:4] == (False, "rejected")


def test_an_example_too_long_or_empty_is_refused():
    with pytest.raises(SessionError, match=f"may hold {QUESTION_CHARS} characters"):
        _ = propose("x" * (QUESTION_CHARS + 1))
    with pytest.raises(SessionError, match="give both"):
        _ = propose(" ")

    assert [row[3] for row in audited()] == ["too_long", "empty"]


def test_a_taken_question_and_a_full_queue_are_refused_with_the_reason():
    _ = propose()
    with pytest.raises(SessionError, match="proposed already"):
        _ = propose()

    _ = propose("Balance of accounts", times=WAITING - 1)
    with pytest.raises(SessionError, match=f"{WAITING} of your proposals"):
        _ = propose("One more")

    assert [row[3] for row in audited() if row[3]] == ["duplicate", "queue_full"]


def test_without_a_store_nothing_is_proposed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    monkeypatch.delenv("FORBQL_STORE_DSN")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FORBQL_DSN_BANK_POSTGRES", READER[Engine.POSTGRES])

    with pytest.raises(SessionError, match="proposals live in the store"):
        _ = propose()
