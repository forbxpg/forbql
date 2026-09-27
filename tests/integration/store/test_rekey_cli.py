"""`forbql store rekey` against the store on the local stand.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from forbql import Engine
from forbql.cli import app
from forbql.store import SecretKey, Store
from support.store import STORE_APP, fresh_store

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("store")]

runner = CliRunner()
OLD = SecretKey.generate()
NEW = SecretKey.generate()
BANK = "postgresql://reader:pa55word@db.internal:5432/bank"


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORBQL_STORE_DSN", fresh_store())
    monkeypatch.setenv("FORBQL_SECRET_KEY", NEW)


def add(key: str, name: str) -> None:
    async def go() -> None:
        async with Store.open(STORE_APP, key=SecretKey.load(key, None)) as store:
            await store.add_connection(name, Engine.POSTGRES, BANK)

    asyncio.run(go())


def opens(key: str, name: str) -> str:
    async def go() -> str:
        async with Store.open(STORE_APP, key=SecretKey.load(key, None)) as store:
            return (await store.dsn(name, "analyst"))[1]

    return asyncio.run(go())


def test_rekey_seals_with_the_key_forbql_now_starts_with(
    monkeypatch: pytest.MonkeyPatch,
):
    add(OLD, "bank")
    add(NEW, "cards")
    monkeypatch.setenv("FORBQL_OLD_SECRET_KEY", OLD)

    result = runner.invoke(app, ["store", "rekey"])

    assert result.exit_code == 0
    new_id = SecretKey.load(NEW, None).key_id
    assert result.stdout == (
        f"sealed 1 DSN again with key {new_id}; 1 already was; restart forbql "
        "with this key\n"
    )
    assert opens(NEW, "bank") == BANK


def test_the_old_key_can_come_from_a_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    add(OLD, "bank")
    _ = (tmp_path / "old").write_text(OLD + "\n", encoding="utf-8")
    monkeypatch.setenv("FORBQL_OLD_SECRET_KEY_FILE", str(tmp_path / "old"))

    result = runner.invoke(app, ["store", "rekey"])

    assert result.exit_code == 0
    assert opens(NEW, "bank") == BANK


def test_without_the_old_key_nothing_happens():
    add(OLD, "bank")

    result = runner.invoke(app, ["store", "rekey"])

    assert result.exit_code == 2
    assert result.stderr == (
        "error: set FORBQL_OLD_SECRET_KEY or FORBQL_OLD_SECRET_KEY_FILE: the key "
        "the DSNs are sealed with now\n"
    )
    assert opens(OLD, "bank") == BANK


def test_a_dsn_neither_key_sealed_is_named(monkeypatch: pytest.MonkeyPatch):
    stranger = SecretKey.generate()
    add(stranger, "bank")
    monkeypatch.setenv("FORBQL_OLD_SECRET_KEY", OLD)

    result = runner.invoke(app, ["store", "rekey"])

    assert result.exit_code == 1
    stranger_id = SecretKey.load(stranger, None).key_id
    assert f"the DSN of bank is sealed with key {stranger_id}" in result.stderr


def test_an_old_key_that_is_no_key_is_refused(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FORBQL_OLD_SECRET_KEY", "not-a-key")

    result = runner.invoke(app, ["store", "rekey"])

    assert result.exit_code == 2
    assert result.stderr == "error: the secret key is not base64url\n"
