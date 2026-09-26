"""A session over the store: DSNs from it, audit records into it.

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
from forbql.store import SecretKey, Store
from support.corpus import DEMO
from support.stand import READER
from support.store import STORE_APP, STORE_OWNER, fresh_store, store_sql

if TYPE_CHECKING:
    from pathlib import Path

    from forbql import RunResult

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("store")]

POLICY = DEMO / "forbql.yaml"
KEY = SecretKey.generate()


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    dsn = fresh_store()
    monkeypatch.setenv("FORBQL_STORE_DSN", dsn)
    monkeypatch.setenv("FORBQL_SECRET_KEY", KEY)
    monkeypatch.delenv("FORBQL_DSN_BANK_POSTGRES", raising=False)
    monkeypatch.chdir(tmp_path)
    return dsn


def keep(engine: Engine) -> None:
    async def go() -> None:
        async with Store.open(STORE_APP, key=SecretKey.load(KEY, None)) as store:
            await store.add_connection("bank-postgres", engine, READER[engine])

    asyncio.run(go())


def run(sql: str = "SELECT count(*) AS n FROM accounts") -> RunResult:
    async def go() -> RunResult:
        async with forbql.connect(
            POLICY,
            connection="bank-postgres",
            profile="analyst",
        ) as session:
            return await session.run(sql)

    return asyncio.run(go())


def audit_count() -> int:
    [[(count,)]] = store_sql(STORE_OWNER, "SELECT count(*) FROM forbql.audit_records")
    return int(str(count))


def test_the_dsn_comes_from_the_store_and_the_record_goes_to_it(tmp_path: Path):
    keep(Engine.POSTGRES)

    result = run()

    assert result.ok
    assert audit_count() == 1
    assert not (tmp_path / "forbql-audit.jsonl").exists()


def test_a_connection_missing_from_the_store_says_how_to_add_it():
    with pytest.raises(SessionError, match="forbql connection add"):
        run()


def test_the_store_and_the_policy_must_agree_on_the_engine():
    keep(Engine.MYSQL)

    with pytest.raises(SessionError, match="as mysql; the policy says postgres"):
        run()


def test_an_outdated_store_refuses_the_session():
    keep(Engine.POSTGRES)
    store_sql(STORE_OWNER, "UPDATE forbql.alembic_version SET version_num = '0000'")

    with pytest.raises(SessionError, match="run `forbql store migrate`"):
        run()


def test_without_the_key_the_dsn_stays_sealed(monkeypatch: pytest.MonkeyPatch):
    keep(Engine.POSTGRES)
    monkeypatch.delenv("FORBQL_SECRET_KEY")

    with pytest.raises(SessionError, match="FORBQL_SECRET_KEY"):
        run()


def test_a_dsn_given_by_the_caller_wins_and_still_audits_to_the_store():
    async def go() -> RunResult:
        async with forbql.connect(
            POLICY,
            connection="bank-postgres",
            profile="analyst",
            dsn=READER[Engine.POSTGRES],
        ) as session:
            return await session.run("SELECT count(*) AS n FROM accounts")

    assert asyncio.run(go()).ok
    assert audit_count() == 1


def test_doctor_checks_the_chain_in_the_store():
    keep(Engine.POSTGRES)
    run()

    result = CliRunner().invoke(
        app,
        ["doctor", "--policy", str(POLICY), "--connection", "bank-postgres"],
    )

    assert result.exit_code == 0, result.stdout
    assert result.stdout.splitlines()[-2:] == [
        "audit chain in the store",
        "  ok       intact; 1 record(s)",
    ]
