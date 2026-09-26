"""The chosen embedding model; the first run downloads it (about 1.1 GB)."""

from __future__ import annotations

import math

import pytest

from forbql.knowledge import MODEL, FastEmbedder

pytestmark = pytest.mark.integration


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def test_a_russian_question_finds_the_english_table_it_means():
    embedder = FastEmbedder()
    loans, carts = embedder.documents(
        ["loans: Loans issued to clients", "carts: Shopping carts not yet ordered"],
    )

    question = embedder.query("Какие кредиты выдали в этом году?")

    assert embedder.name == MODEL
    assert len(question) == 1024
    assert cosine(question, loans) > cosine(question, carts)
