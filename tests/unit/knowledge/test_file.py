from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from forbql.knowledge import (
    Example,
    GlossaryTerm,
    KnowledgeError,
    load_knowledge,
    parse_knowledge,
)

if TYPE_CHECKING:
    from pathlib import Path

FILE = """
glossary:
  - term: active account
    definition: An account still open.
    table: public.accounts
    sql: status = 'open'
  - term: fiscal year
    definition: Starts on the first of April.
examples:
  - question: Money on accounts per currency
    sql: SELECT currency, sum(balance) FROM accounts GROUP BY currency
"""


def test_reads_terms_and_examples():
    knowledge = parse_knowledge(FILE)

    assert knowledge.glossary == (
        GlossaryTerm(
            term="active account",
            definition="An account still open.",
            table="public.accounts",
            sql="status = 'open'",
        ),
        GlossaryTerm(term="fiscal year", definition="Starts on the first of April."),
    )
    assert knowledge.examples == (
        Example(
            question="Money on accounts per currency",
            sql="SELECT currency, sum(balance) FROM accounts GROUP BY currency",
        ),
    )


def test_an_empty_file_holds_nothing():
    knowledge = parse_knowledge("")

    assert (knowledge.glossary, knowledge.examples) == ((), ())


def test_what_search_matches_and_what_is_checked_for_names():
    term, plain = parse_knowledge(FILE).glossary
    [example] = parse_knowledge(FILE).examples

    assert term.body == "active account: An account still open."
    assert term.text == "active account: An account still open.\nstatus = 'open'"
    assert plain.text == "fiscal year: Starts on the first of April."
    assert example.body == "Money on accounts per currency"
    assert example.text.endswith("GROUP BY currency")


def test_any_change_changes_the_hash():
    term = GlossaryTerm(term="t", definition="d", table="public.a", sql="x = 1")

    assert term.body_hash != term.model_copy(update={"sql": "x = 2"}).body_hash
    assert term.body_hash == GlossaryTerm.model_validate(term.model_dump()).body_hash


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("glossary: [{term: t, definition: d, table: public.a}]", "go together"),
        ("glossary: [{term: t, definition: d, sql: x = 1}]", "go together"),
        (
            "glossary: [{term: t, definition: d}, {term: T, definition: e}]",
            "term appears more than once: t",
        ),
        (
            "examples: [{question: q, sql: SELECT 1}, {question: q, sql: SELECT 2}]",
            "question appears more than once: q",
        ),
        ("glossary: [{term: t, definition: d, owner: me}]", "Extra inputs"),
        ("glossary: [{term: '', definition: d}]", "at least 1 character"),
        ("glossary:\n  - term: t\n    term: u\n    definition: d", "duplicate key"),
        ("glossary: [", "invalid YAML"),
    ],
)
def test_a_broken_file_fails_with_the_reason(text: str, message: str):
    with pytest.raises(KnowledgeError, match=message):
        _ = parse_knowledge(text)


def test_loads_from_a_file(tmp_path: Path):
    path = tmp_path / "knowledge.yaml"
    _ = path.write_text(FILE, encoding="utf-8")

    assert len(load_knowledge(path).glossary) == 2


def test_missing_file_is_a_knowledge_error(tmp_path: Path):
    with pytest.raises(KnowledgeError, match="cannot read"):
        _ = load_knowledge(tmp_path / "absent.yaml")
