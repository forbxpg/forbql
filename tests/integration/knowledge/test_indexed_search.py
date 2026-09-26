"""Indexing a synced schema and searching it, with a test embedder.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from forbql.firewall import ColumnInfo, ForeignKey, SchemaCatalog, TableInfo
from forbql.knowledge import IndexChange, SearchHit, index_catalog, search
from forbql.store import Store
from support.embedding import WordEmbedder
from support.store import STORE_APP, fresh_store

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("store")]

EMBEDDER = WordEmbedder()


def column(name: str, comment: str | None = None) -> ColumnInfo:
    return ColumnInfo(name=name, type="integer", nullable=False, comment=comment)


CLIENTS = TableInfo(
    columns=(column("id"), column("passport", "identity document")),
    primary_key=("id",),
    comment="Bank clients",
)
ACCOUNTS = TableInfo(
    columns=(
        column("id"),
        column("client_id"),
        column("balance", "money on the account"),
    ),
    primary_key=("id",),
    foreign_keys=(
        ForeignKey(columns=("client_id",), table="public.clients", references=("id",)),
    ),
    comment="Client accounts",
)
SECRETS = TableInfo(columns=(column("id"),), comment="money keys")
CATALOG = SchemaCatalog(
    default_schema="public",
    tables={
        "public.clients": CLIENTS,
        "public.accounts": ACCOUNTS,
        "public.secrets": SECRETS,
    },
)
VISIBLE = {"public.clients": ("id",), "public.accounts": ("id", "client_id", "balance")}


@pytest.fixture
def store() -> str:
    return fresh_store()


def with_store[T](work: Callable[[Store], Awaitable[T]]) -> T:
    async def go() -> T:
        async with Store.open(STORE_APP) as store:
            return await work(store)

    return asyncio.run(go())


def index(catalog: SchemaCatalog = CATALOG, *, everything: bool = False) -> IndexChange:
    return with_store(
        lambda store: index_catalog(
            store,
            EMBEDDER,
            "bank",
            catalog,
            everything=everything,
        ),
    )


def find(
    question: str,
    visible: Mapping[str, Sequence[str]] = VISIBLE,
) -> list[SearchHit]:
    return with_store(
        lambda store: search(
            store,
            EMBEDDER,
            CATALOG,
            visible,
            connection="bank",
            question=question,
        ),
    )


def test_indexing_embeds_only_what_changed():
    first = index()
    again = index()
    commented = index(
        CATALOG.model_copy(
            update={
                "tables": {
                    **CATALOG.tables,
                    "public.clients": CLIENTS.model_copy(update={"comment": "People"}),
                },
            },
        ),
    )
    dropped = index(
        CATALOG.model_copy(update={"tables": {"public.clients": CLIENTS}}),
    )
    rebuilt = index(everything=True)

    assert first == IndexChange(embedded=9, removed=0)
    assert again == IndexChange(embedded=0, removed=0)
    assert commented == IndexChange(embedded=1, removed=0)
    assert dropped == IndexChange(embedded=1, removed=6)
    assert rebuilt == IndexChange(embedded=9, removed=0)


def test_a_match_brings_the_table_it_joins():
    index()

    hits = find("balance")

    assert hits[:2] == [
        SearchHit(table="public.accounts", columns=("id", "client_id", "balance")),
        SearchHit(
            table="public.clients",
            columns=("id",),
            joined_from="public.accounts",
        ),
    ]


def test_what_the_profile_cannot_see_is_never_found():
    index()

    hits = find("money identity document keys")

    assert {hit.table for hit in hits} <= set(VISIBLE)
    assert "passport" not in [c for hit in hits for c in hit.columns]
