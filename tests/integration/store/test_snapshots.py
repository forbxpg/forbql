"""Schema snapshots in the store: a version per sync, none ever changed.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import asyncpg
import pytest

from forbql.firewall import ColumnInfo, SchemaCatalog, TableInfo
from forbql.store import Store
from support.store import STORE_APP, fresh_store, store_sql

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("store")]


@pytest.fixture
def store() -> str:
    return fresh_store()


def catalog(*columns: str) -> SchemaCatalog:
    return SchemaCatalog(
        default_schema="public",
        tables={
            "public.accounts": TableInfo(
                columns=tuple(
                    ColumnInfo(name=name, type="integer", nullable=False, comment="ё")
                    for name in columns
                ),
                primary_key=("id",),
            ),
        },
    )


def with_store[T](work: Callable[[Store], Awaitable[T]]) -> T:
    async def go() -> T:
        async with Store.open(STORE_APP) as store:
            return await work(store)

    return asyncio.run(go())


def test_there_is_no_snapshot_before_the_first_sync():
    assert with_store(lambda store: store.snapshots.latest("bank")) is None


def test_a_snapshot_reads_back_as_it_was_kept():
    kept = with_store(
        lambda store: store.snapshots.add("bank", catalog("id", "balance")),
    )

    latest = with_store(lambda store: store.snapshots.latest("bank"))

    assert kept.version == 1
    assert latest == kept


def test_each_sync_adds_a_version_per_connection():
    with_store(lambda store: store.snapshots.add("bank", catalog("id")))
    with_store(lambda store: store.snapshots.add("bank", catalog("id", "balance")))
    with_store(lambda store: store.snapshots.add("shop", catalog("id")))

    bank = with_store(lambda store: store.snapshots.latest("bank"))
    shop = with_store(lambda store: store.snapshots.latest("shop"))

    assert bank is not None
    assert shop is not None
    assert (bank.version, shop.version) == (2, 1)
    assert [c.name for c in bank.catalog.tables["public.accounts"].columns] == [
        "id",
        "balance",
    ]


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE forbql.schema_snapshots SET content_hash = 'x'",
        "DELETE FROM forbql.schema_snapshots",
    ],
)
def test_the_runtime_role_cannot_rewrite_a_snapshot(sql: str):
    with_store(lambda store: store.snapshots.add("bank", catalog("id")))

    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        store_sql(STORE_APP, sql)
