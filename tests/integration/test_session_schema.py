"""With a store, the firewall sees what is in the database and in the last sync.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest

import forbql
from forbql import Engine, RuleId, SessionError
from forbql.session import schema_changes, sync_schema
from forbql.store import SecretKey, Store
from support.corpus import DEMO
from support.stand import READER, as_owner
from support.store import STORE_APP, fresh_store

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from forbql import RunResult

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("store")]

POLICY = DEMO / "forbql.yaml"
CONNECTION = "bank-postgres"
KEY = SecretKey.generate()


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FORBQL_STORE_DSN", fresh_store())
    monkeypatch.setenv("FORBQL_SECRET_KEY", KEY)
    monkeypatch.chdir(tmp_path)

    async def go() -> None:
        async with Store.open(STORE_APP, key=SecretKey.load(KEY, None)) as opened:
            await opened.add_connection(
                CONNECTION,
                Engine.POSTGRES,
                READER[Engine.POSTGRES],
            )

    asyncio.run(go())


@contextmanager
def note_column() -> Generator[None]:
    as_owner(Engine.POSTGRES, ["ALTER TABLE accounts ADD COLUMN note text"])
    try:
        yield
    finally:
        as_owner(Engine.POSTGRES, ["ALTER TABLE accounts DROP COLUMN IF EXISTS note"])


def sync():
    return asyncio.run(sync_schema(POLICY, connection=CONNECTION))


def run(sql: str) -> tuple[RunResult, tuple[str, ...]]:
    async def go() -> tuple[RunResult, tuple[str, ...]]:
        async with forbql.connect(
            POLICY,
            connection=CONNECTION,
            profile="analyst",
        ) as s:
            return await s.run(sql), s.warnings

    return asyncio.run(go())


def test_without_a_synced_schema_the_session_refuses():
    with pytest.raises(SessionError, match="forbql schema sync bank-postgres"):
        run("SELECT count(*) FROM accounts")


def test_the_first_sync_lists_every_table_and_a_second_changes_nothing():
    first = sync()
    second = sync()

    assert first.version == 1
    assert "+ table public.accounts" in first.changes
    assert "+ view public.account_totals" in first.changes
    assert second.version == 1
    assert second.changes == ()


def test_a_column_added_after_the_sync_stays_unseen_until_the_next():
    sync()
    with note_column():
        unseen, warnings = run("SELECT note FROM accounts")
        changes = asyncio.run(schema_changes(POLICY, connection=CONNECTION))
        synced = sync()
        seen, after = run("SELECT note FROM accounts")

    assert [v.rule for v in unseen.verdict.violations] == [RuleId.UNKNOWN_COLUMN]
    assert warnings == (
        (
            "bank-postgres changed since the last sync (1 changes, unseen until "
            "synced): see `forbql schema diff bank-postgres`"
        ),
    )
    assert changes == ["+ column public.accounts.note text"]
    assert synced.changes == ("+ column public.accounts.note text",)
    assert seen.ok
    assert after == ()


def test_a_column_dropped_after_the_sync_is_gone_at_once():
    with note_column():
        sync()
        as_owner(Engine.POSTGRES, ["ALTER TABLE accounts DROP COLUMN note"])
        result, warnings = run("SELECT note FROM accounts")

    assert [v.rule for v in result.verdict.violations] == [RuleId.UNKNOWN_COLUMN]
    assert len(warnings) == 1


def test_diff_before_any_sync_says_what_to_run():
    with pytest.raises(SessionError, match="run `forbql schema sync bank-postgres`"):
        asyncio.run(schema_changes(POLICY, connection=CONNECTION))
