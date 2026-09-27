"""Sealing every DSN again under a new key.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from forbql import Engine
from forbql.store import Rekeyed, SecretKey, Store, StoreError
from support.store import STORE_APP, STORE_SUPERUSER, fresh_store, store_sql

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("store")]

OLD = SecretKey(b"o" * 32)
NEW = SecretKey(b"n" * 32)
OTHER = SecretKey(b"x" * 32)
BANK = "postgresql://reader:pa55word@db.internal:5432/bank"
ANALYST = "postgresql://analyst:an4lyst@db.internal:5432/bank"


@pytest.fixture
def store() -> str:
    return fresh_store()


def with_store[T](work: Callable[[Store], Awaitable[T]], key: SecretKey) -> T:
    async def go() -> T:
        async with Store.open(STORE_APP, key=key) as store:
            return await work(store)

    return asyncio.run(go())


def add(key: SecretKey, name: str, dsn: str, profile: str | None = None) -> None:
    with_store(
        lambda store: store.add_connection(name, Engine.POSTGRES, dsn, profile=profile),
        key,
    )


def dsn(key: SecretKey, name: str, profile: str) -> str:
    return with_store(lambda store: store.dsn(name, profile), key)[1]


def rekey(old: SecretKey) -> Rekeyed:
    return with_store(lambda store: store.rekey(old), NEW)


def key_ids() -> list[str]:
    rows = store_sql(
        STORE_SUPERUSER,
        "SELECT key_id FROM forbql.connection_secrets ORDER BY profile",
    )
    return [str(row[0]) for row in rows[0]]


def test_every_dsn_opens_with_the_new_key_and_not_the_old():
    add(OLD, "bank", BANK)
    add(OLD, "bank", ANALYST, profile="analyst")

    assert rekey(OLD) == Rekeyed(NEW.key_id, 2, 0)

    assert dsn(NEW, "bank", "clerk") == BANK
    assert dsn(NEW, "bank", "analyst") == ANALYST
    with pytest.raises(StoreError, match="sealed with key"):
        _ = dsn(OLD, "bank", "clerk")


def test_running_it_again_changes_nothing():
    add(OLD, "bank", BANK)
    add(NEW, "cards", BANK)

    assert rekey(OLD) == Rekeyed(NEW.key_id, 1, 1)
    assert rekey(OLD) == Rekeyed(NEW.key_id, 0, 2)
    assert dsn(NEW, "bank", "clerk") == BANK


def test_a_dsn_under_a_third_key_leaves_every_dsn_as_it_was():
    add(OLD, "bank", BANK)
    add(OTHER, "cards", BANK)
    before = key_ids()

    with pytest.raises(StoreError, match=f"key {OTHER.key_id}.*nothing was changed"):
        _ = rekey(OLD)

    assert key_ids() == before
    assert dsn(OLD, "bank", "clerk") == BANK


def test_the_old_key_must_differ_from_the_new():
    add(NEW, "bank", BANK)

    with pytest.raises(StoreError, match="the same key"):
        _ = rekey(NEW)
