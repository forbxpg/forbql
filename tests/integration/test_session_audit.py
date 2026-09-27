"""Every call a session answers leaves a record naming its kind, on the stand.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

import forbql
from forbql import Engine, SessionError
from forbql.session import sync_schema
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

    asyncio.run(go())


def records(
    tmp_path: Path,
    work: Callable[[Session], Awaitable[object]],
) -> list[dict[str, object]]:
    log = tmp_path / "audit.jsonl"

    async def go() -> None:
        async with forbql.connect(
            POLICY,
            connection=CONNECTION,
            profile="analyst",
            dsn=READER[Engine.POSTGRES],
            audit_log=log,
        ) as session:
            _ = await work(session)

    asyncio.run(go())
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


@pytest.mark.usefixtures("store")
def test_a_check_is_recorded_and_runs_nothing(tmp_path: Path):
    async def work(session: Session) -> None:
        _ = await session.check("SELECT count(*) FROM accounts")
        _ = await session.check("SELECT passport FROM clients")

    allowed, rejected = records(tmp_path, work)

    assert (allowed["action"], allowed["allowed"], allowed["executed_sql"]) == (
        "sql.check",
        True,
        None,
    )
    assert (rejected["action"], rejected["allowed"]) == ("sql.check", False)
    assert rejected["rules"]


@pytest.mark.usefixtures("store")
def test_a_search_is_recorded_with_the_question(tmp_path: Path):
    [found] = records(tmp_path, lambda session: session.search("currency"))

    assert (found["action"], found["sql"], found["allowed"]) == (
        "schema.search",
        "currency",
        True,
    )
    assert found["rows"] != 0


def test_a_search_without_a_store_is_recorded_as_refused(tmp_path: Path):
    async def work(session: Session) -> None:
        with pytest.raises(SessionError):
            _ = await session.search("currency")

    [refused] = records(tmp_path, work)

    assert (refused["action"], refused["allowed"], refused["error_class"]) == (
        "schema.search",
        False,
        "no_store",
    )


def test_a_run_is_recorded_as_a_run(tmp_path: Path):
    [ran] = records(tmp_path, lambda session: session.run("SELECT 1 AS one"))

    assert (ran["action"], ran["executed_sql"] is not None) == ("sql.run", True)
