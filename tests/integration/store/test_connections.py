"""Connections in the store: DSNs sealed at rest, opened for the profile that asks.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from forbql import Engine
from forbql.store import SecretKey, Store, StoredConnection, StoreError
from support.store import (
    STORE_APP,
    STORE_SUPERUSER,
    empty_store,
    fresh_store,
    store_sql,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("store")]

KEY = SecretKey(b"k" * 32)
BANK = "postgresql://reader:pa55word@db.internal:5432/bank"
ANALYST = "postgresql://analyst:an4lyst@db.internal:5432/bank"


@pytest.fixture
def store() -> str:
    return fresh_store()


def with_store[T](
    work: Callable[[Store], Awaitable[T]],
    key: SecretKey | None = KEY,
    dsn: str = STORE_APP,
) -> T:
    async def go() -> T:
        async with Store.open(dsn, key=key) as store:
            return await work(store)

    return asyncio.run(go())


def add(name: str, dsn: str, profile: str | None = None) -> None:
    with_store(
        lambda store: store.add_connection(name, Engine.POSTGRES, dsn, profile=profile),
    )


def test_a_dsn_comes_back_for_any_profile():
    add("bank", BANK)

    assert with_store(lambda store: store.dsn("bank", "analyst")) == (
        Engine.POSTGRES,
        BANK,
    )


def test_a_dsn_is_sealed_at_rest():
    add("bank", BANK)

    [[(sealed,)]] = store_sql(
        STORE_SUPERUSER,
        "SELECT sealed FROM forbql.connection_secrets",
    )

    assert isinstance(sealed, bytes)
    assert b"pa55word" not in sealed
    assert b"db.internal" not in sealed


def test_a_profile_with_its_own_dsn_gets_it_and_the_others_do_not():
    add("bank", BANK)
    add("bank", ANALYST, profile="analyst")

    assert with_store(lambda store: store.dsn("bank", "analyst"))[1] == ANALYST
    assert with_store(lambda store: store.dsn("bank", "auditor"))[1] == BANK


def test_adding_again_replaces_the_dsn():
    add("bank", BANK)
    add("bank", ANALYST)

    assert with_store(lambda store: store.dsn("bank", "analyst"))[1] == ANALYST


def test_a_connection_keeps_its_engine():
    add("bank", BANK)

    with pytest.raises(StoreError, match="is postgres, not mysql"):
        with_store(lambda store: store.add_connection("bank", Engine.MYSQL, BANK))


def test_the_list_names_connections_and_profiles_never_dsns():
    add("bank", BANK)
    add("bank", ANALYST, profile="analyst")
    add("shop", BANK)

    assert with_store(lambda store: store.connections()) == [
        StoredConnection(name="bank", engine=Engine.POSTGRES, profiles=("analyst",)),
        StoredConnection(name="shop", engine=Engine.POSTGRES, profiles=()),
    ]


def test_removing_a_profile_keeps_the_connection():
    add("bank", BANK)
    add("bank", ANALYST, profile="analyst")

    assert with_store(lambda store: store.remove_connection("bank", profile="analyst"))
    assert with_store(lambda store: store.dsn("bank", "analyst"))[1] == BANK


def test_removing_a_connection_forgets_its_dsns():
    add("bank", BANK)

    assert with_store(lambda store: store.remove_connection("bank"))
    assert not with_store(lambda store: store.remove_connection("bank"))
    with pytest.raises(StoreError, match="no DSN for connection 'bank'"):
        with_store(lambda store: store.dsn("bank", "analyst"))


def test_no_key_no_dsn():
    add("bank", BANK)

    with pytest.raises(StoreError, match="FORBQL_SECRET_KEY"):
        with_store(lambda store: store.dsn("bank", "analyst"), key=None)


def test_another_key_cannot_open_it():
    add("bank", BANK)

    with pytest.raises(StoreError, match="sealed with key"):
        with_store(lambda store: store.dsn("bank", "analyst"), key=SecretKey(b"o" * 32))


def test_a_dsn_copied_to_another_connection_does_not_open():
    add("bank", BANK)
    add("shop", ANALYST)
    store_sql(
        STORE_SUPERUSER,
        """
        UPDATE forbql.connection_secrets AS target SET sealed = source.sealed
        FROM forbql.connection_secrets AS source
        JOIN forbql.connections AS c ON c.id = source.connection_id AND c.name = 'bank'
        WHERE target.connection_id = (
            SELECT id FROM forbql.connections WHERE name = 'shop'
        )
        """,
    )

    with pytest.raises(StoreError, match="changed or moved"):
        with_store(lambda store: store.dsn("shop", "analyst"))


def test_a_store_that_was_never_migrated_is_refused():
    empty_store()

    with pytest.raises(StoreError, match="run `forbql store migrate`"):
        with_store(lambda store: store.connections())


def test_an_unreachable_store_is_refused():
    with pytest.raises(StoreError, match="cannot reach the store"):
        with_store(
            lambda store: store.connections(),
            dsn="postgresql://forbql_app:wrong@127.0.0.1:55432/forbql_test",
        )
