"""`forbql schema sync` and `diff` against the stand.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio

import pytest
from typer.testing import CliRunner

from forbql import Engine
from forbql.cli import app
from forbql.store import SecretKey, Store
from support.corpus import DEMO
from support.stand import READER, as_owner
from support.store import STORE_APP, fresh_store

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("store")]

runner = CliRunner()
KEY = SecretKey.generate()


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORBQL_STORE_DSN", fresh_store())
    monkeypatch.setenv("FORBQL_SECRET_KEY", KEY)
    monkeypatch.setenv("FORBQL_POLICY", str(DEMO / "forbql.yaml"))

    async def go() -> None:
        async with Store.open(STORE_APP, key=SecretKey.load(KEY, None)) as opened:
            await opened.add_connection(
                "bank-postgres",
                Engine.POSTGRES,
                READER[Engine.POSTGRES],
            )

    asyncio.run(go())


def schema(*args: str):
    return runner.invoke(app, ["schema", *args])


def test_sync_prints_the_version_and_what_it_holds():
    first = schema("sync", "bank-postgres")
    again = schema("sync", "bank-postgres")

    assert first.exit_code == 0
    assert first.stdout.splitlines()[0] == "bank-postgres: version 1"
    assert "  + table public.accounts" in first.stdout.splitlines()
    assert again.stdout == "bank-postgres: no changes; still version 1\n"


def test_diff_exits_one_when_the_schema_moved():
    schema("sync", "bank-postgres")
    as_owner(Engine.POSTGRES, ["COMMENT ON TABLE accounts IS 'Changed'"])
    try:
        moved = schema("diff", "bank-postgres")
    finally:
        as_owner(
            Engine.POSTGRES,
            [
                "COMMENT ON TABLE accounts IS 'Client accounts; a client may hold several'",
            ],
        )
    still = schema("diff", "bank-postgres")

    assert moved.exit_code == 1
    assert moved.stdout == "~ table public.accounts: comment\n"
    assert still.exit_code == 0
    assert still.stdout == "bank-postgres: no changes since the last sync\n"


def test_a_connection_outside_the_store_is_a_refusal():
    result = schema("sync", "bank-mysql")

    assert result.exit_code == 2
    assert "forbql connection add" in result.stderr
