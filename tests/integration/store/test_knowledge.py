"""Glossary terms and examples in the store: only allowed entries are ranked.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from forbql.store import (
    KnowledgeKind,
    Store,
    StoredExample,
    StoredTerm,
    StoreError,
)
from support.embedding import WordEmbedder
from support.store import STORE_APP, fresh_store, store_sql

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("store")]

EMBEDDER = WordEmbedder()
OPEN = StoredTerm(
    term="open account",
    definition="An account still in use",
    table="public.accounts",
    sql="status = 'open'",
    body_hash="h1",
    model=EMBEDDER.name,
)
PAYROLL = StoredTerm(
    term="payroll",
    definition="Money paid to staff",
    table=None,
    sql=None,
    body_hash="h2",
    model=EMBEDDER.name,
)
BALANCES = StoredExample(
    question="Money on accounts per currency",
    sql="SELECT currency, sum(balance) FROM accounts GROUP BY currency",
    body_hash="h3",
    model=EMBEDDER.name,
)


@pytest.fixture
def store() -> str:
    return fresh_store()


def with_store[T](work: Callable[[Store], Awaitable[T]]) -> T:
    async def go() -> T:
        async with Store.open(STORE_APP) as store:
            return await work(store)

    return asyncio.run(go())


def vector(text: str) -> list[float]:
    [found] = EMBEDDER.documents([text])
    return found


def load(
    terms: Sequence[StoredTerm] = (OPEN, PAYROLL),
    examples: Sequence[StoredExample] = (BALANCES,),
) -> None:
    with_store(
        lambda store: store.knowledge.update(
            "bank",
            terms=[(t, vector(f"{t.term}: {t.definition}")) for t in terms],
            examples=[(e, vector(e.question)) for e in examples],
        ),
    )


def ranked(
    kind: KnowledgeKind,
    question: str,
    allowed: Sequence[str],
    model: str = EMBEDDER.name,
) -> tuple[list[str], list[str]]:
    return with_store(
        lambda store: store.knowledge.ranked(
            "bank",
            kind,
            text_query=question,
            vector=EMBEDDER.query(question),
            model=model,
            allowed=allowed,
            limit=5,
        ),
    )


def test_entries_read_back_as_written():
    load()

    terms = with_store(lambda store: store.knowledge.terms("bank"))
    examples = with_store(lambda store: store.knowledge.examples("bank"))

    assert terms == [OPEN, PAYROLL]
    assert examples == [BALANCES]


def test_a_changed_entry_replaces_the_old_one():
    load()
    changed = replace(OPEN, definition="Not closed")

    load(terms=[changed], examples=[])

    assert with_store(lambda store: store.knowledge.terms("bank"))[0] == changed


def test_removed_entries_leave_the_store():
    load()

    with_store(
        lambda store: store.knowledge.update(
            "bank",
            removed_terms=["payroll"],
            removed_examples=[BALANCES.question],
        ),
    )

    assert with_store(lambda store: store.knowledge.terms("bank")) == [OPEN]
    assert with_store(lambda store: store.knowledge.examples("bank")) == []


def test_a_refused_entry_changes_nothing():
    load()
    broken = replace(OPEN, term="broken", sql=None)

    with pytest.raises(StoreError, match="sql_with_table"):
        with_store(
            lambda store: store.knowledge.update(
                "bank",
                terms=[(broken, vector("broken"))],
                removed_terms=["payroll"],
            ),
        )

    assert with_store(lambda store: store.knowledge.terms("bank")) == [OPEN, PAYROLL]


def test_only_allowed_entries_are_ranked():
    load()

    by_meaning, by_words = ranked(
        KnowledgeKind.GLOSSARY,
        "money paid",
        ["open account"],
    )

    assert "payroll" not in by_meaning + by_words
    assert by_meaning == ["open account"]


def test_both_rankings_find_what_matches():
    load()

    by_meaning, by_words = ranked(
        KnowledgeKind.GLOSSARY,
        "money paid",
        ["open account", "payroll"],
    )
    examples = ranked(KnowledgeKind.EXAMPLES, "currency", [BALANCES.question])

    assert by_meaning[0] == "payroll"
    assert by_words == ["payroll"]
    assert examples == ([BALANCES.question], [BALANCES.question])


def test_vectors_of_another_model_are_skipped():
    load()

    by_meaning, by_words = ranked(
        KnowledgeKind.GLOSSARY,
        "payroll",
        ["open account", "payroll"],
        model="old/model",
    )

    assert by_meaning == []
    assert by_words == ["payroll"]


def test_the_runtime_role_may_replace_knowledge():
    rows = store_sql(
        STORE_APP,
        "SELECT has_table_privilege('forbql.glossary_terms', 'INSERT, DELETE')",
        "SELECT has_table_privilege('forbql.examples', 'INSERT, DELETE')",
    )

    assert rows == [[(True,)], [(True,)]]
