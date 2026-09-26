"""The search index in the store: visibility applies before anything is ranked.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from forbql.store import IndexedDocument, Store
from support.embedding import WordEmbedder
from support.store import STORE_APP, fresh_store

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("store")]

EMBEDDER = WordEmbedder()
BODIES = {
    ("public.clients", ""): "clients: people who bank with us",
    ("public.clients", "id"): "clients id",
    ("public.clients", "passport"): "clients passport (identity document number)",
    ("public.accounts", ""): "accounts: money a client holds",
    ("public.accounts", "balance"): "accounts balance",
    ("public.secrets", ""): "secrets: identity keys",
}


@pytest.fixture
def store() -> str:
    return fresh_store()


def with_store[T](work: Callable[[Store], Awaitable[T]]) -> T:
    async def go() -> T:
        async with Store.open(STORE_APP) as store:
            return await work(store)

    return asyncio.run(go())


def document(key: tuple[str, str], model: str = EMBEDDER.name) -> IndexedDocument:
    body = BODIES[key]
    [vector] = EMBEDDER.documents([body])
    return IndexedDocument(
        table=key[0],
        column=key[1],
        body=body,
        body_hash=f"hash:{body}",
        model=model,
        embedding=vector,
    )


def index(
    documents: list[IndexedDocument],
    removed: Sequence[tuple[str, str]] = (),
) -> None:
    with_store(lambda store: store.search.update("bank", documents, removed))


def ranked(
    question: str,
    visible: Mapping[str, Sequence[str]],
) -> tuple[list[str], list[str]]:
    return with_store(
        lambda store: store.search.ranked(
            "bank",
            text_query=question,
            vector=EMBEDDER.query(question),
            model=EMBEDDER.name,
            visible=visible,
            limit=20,
        ),
    )


def test_the_index_says_what_it_holds():
    index([document(key) for key in BODIES])

    held = with_store(lambda store: store.search.indexed("bank"))

    assert held["public.clients", "passport"] == (
        "hash:clients passport (identity document number)",
        EMBEDDER.name,
    )
    assert len(held) == len(BODIES)


def test_a_hidden_column_does_not_pull_its_table_up():
    index([document(key) for key in BODIES])

    hidden = ranked(
        "passport",
        {"public.clients": ("id",), "public.accounts": ("balance",)},
    )
    shown = ranked("passport", {"public.clients": ("id", "passport")})

    assert hidden[1] == []
    assert shown[1] == ["public.clients"]


def test_a_hidden_table_never_ranks():
    index([document(key) for key in BODIES])

    by_meaning, by_words = ranked("identity", {"public.clients": ("id",)})

    assert "public.secrets" not in by_meaning + by_words
    assert by_meaning == ["public.clients"]


def test_vectors_of_another_model_are_skipped():
    index([document(("public.accounts", ""), model="old/model")])

    by_meaning, by_words = ranked("money", {"public.accounts": ()})

    assert by_meaning == []
    assert by_words == ["public.accounts"]


def test_removed_documents_leave_the_index():
    index([document(key) for key in BODIES])

    index([], removed=[("public.clients", "passport"), ("public.secrets", "")])

    held = with_store(lambda store: store.search.indexed("bank"))
    assert ("public.clients", "passport") not in held
    assert ("public.secrets", "") not in held
    assert len(held) == len(BODIES) - 2
