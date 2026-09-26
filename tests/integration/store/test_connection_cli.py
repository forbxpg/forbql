"""`forbql connection` against the store on the local stand.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
import os

import pytest
from typer.testing import CliRunner

from forbql import Engine
from forbql.cli import app
from forbql.store import SecretKey, Store
from support.store import STORE_APP, STORE_SUPERUSER, fresh_store, store_sql

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("store")]

runner = CliRunner()
BANK = "postgresql://reader:pa55word@db.internal:5432/bank"


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORBQL_STORE_DSN", fresh_store())
    monkeypatch.setenv("FORBQL_SECRET_KEY", SecretKey.generate())


def invoke(*args: str, stdin: str | None = None):
    return runner.invoke(app, ["connection", *args], input=stdin)


def test_add_reads_the_dsn_from_standard_input():
    result = invoke("add", "bank", "--engine", "postgres", stdin=BANK + "\n")

    assert result.exit_code == 0
    assert result.stdout == "sealed the DSN of bank\n"
    assert "pa55word" not in result.output
    assert stored_dsn("bank") == (Engine.POSTGRES, BANK)


def stored_dsn(name: str) -> tuple[Engine, str]:
    key = SecretKey.load(os.environ["FORBQL_SECRET_KEY"], None)

    async def go() -> tuple[Engine, str]:
        async with Store.open(STORE_APP, key=key) as store:
            return await store.dsn(name, "analyst")

    return asyncio.run(go())


def test_list_shows_what_is_there_and_no_dsn():
    invoke("add", "bank", "--engine", "postgres", stdin=BANK)
    invoke("add", "bank", "--engine", "postgres", "--profile", "analyst", stdin=BANK)

    result = invoke("list")

    assert result.stdout == "bank  postgres  own DSN: analyst\n"


def test_remove_says_what_went():
    invoke("add", "bank", "--engine", "postgres", stdin=BANK)

    assert invoke("remove", "bank").stdout == "removed bank\n"
    missing = invoke("remove", "bank")
    assert missing.exit_code == 1
    assert missing.stderr == "error: no bank in the store\n"


def test_without_a_key_nothing_is_sealed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("FORBQL_SECRET_KEY")

    result = invoke("add", "bank", "--engine", "postgres", stdin=BANK)

    assert result.exit_code == 1
    assert "FORBQL_SECRET_KEY" in result.stderr
    assert store_sql(STORE_SUPERUSER, "SELECT count(*) FROM forbql.connections") == [
        [(0,)],
    ]


def test_without_a_store_the_command_says_which_variable(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("FORBQL_STORE_DSN")

    result = invoke("list")

    assert result.exit_code == 2
    assert "FORBQL_STORE_DSN" in result.stderr
