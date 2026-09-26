"""Schema search on the evaluation set, with the real model: at least 95% found.

A question counts as found when every table its query needs is among the results.
The first run downloads the model (about 1.1 GB).

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio

import pytest

from forbql.knowledge import FastEmbedder, index_catalog, search
from forbql.store import Store
from support.search_eval import eval_catalog, eval_questions
from support.store import STORE_APP, fresh_store

pytestmark = pytest.mark.integration

BAR = 0.95


def test_search_finds_what_questions_need():
    fresh_store()
    catalog = eval_catalog()
    questions = eval_questions()
    embedder = FastEmbedder()
    visible = {
        name: tuple(c.name for c in t.columns) for name, t in catalog.tables.items()
    }

    async def go() -> list[str]:
        async with Store.open(STORE_APP) as store:
            _ = await index_catalog(store, embedder, "eval", catalog)
            missed: list[str] = []
            for question in questions:
                hits = await search(
                    store,
                    embedder,
                    catalog,
                    visible,
                    connection="eval",
                    question=question.text,
                )
                if not question.tables <= {hit.table for hit in hits}:
                    missed.append(question.text)
            return missed

    missed = asyncio.run(go())

    found = 1 - len(missed) / len(questions)
    assert found >= BAR, f"{found:.1%} found; missed: {missed}"
