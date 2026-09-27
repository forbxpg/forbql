"""Proposed examples in the store: a bounded queue, approval, rejection.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from forbql.store import (
    ProposalError,
    Refusal,
    Store,
    StoredExample,
    StoredProposal,
)
from support.embedding import WordEmbedder
from support.store import STORE_APP, fresh_store

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("store")]

EMBEDDER = WordEmbedder()
BANK = "bank"
QUESTION = "Money on accounts per currency"
SQL = "SELECT currency, sum(balance) FROM accounts GROUP BY currency"
AGENT = "token:0123456789ab"


@pytest.fixture
def store() -> str:
    return fresh_store()


def with_store[T](work: Callable[[Store], Awaitable[T]]) -> T:
    async def go() -> T:
        async with Store.open(STORE_APP) as store:
            return await work(store)

    return asyncio.run(go())


def propose(
    question: str = QUESTION,
    *,
    author: str = AGENT,
    connection: str = BANK,
    waiting: int = 20,
) -> int:
    return with_store(
        lambda store: store.proposals.add(
            connection,
            profile="analyst",
            question=question,
            sql=SQL,
            author=author,
            waiting=waiting,
        ),
    )


def example(question: str = QUESTION) -> StoredExample:
    return StoredExample(
        question=question,
        sql=SQL,
        body_hash="h",
        model=EMBEDDER.name,
    )


def approve(number: int, question: str = QUESTION) -> None:
    with_store(
        lambda store: store.proposals.approve(
            number,
            by="local:operator",
            example=example(question),
            vector=EMBEDDER.query(question),
        ),
    )


def waiting(connection: str | None = None) -> list[StoredProposal]:
    return with_store(lambda store: store.proposals.listed(connection=connection))


def approved() -> list[StoredProposal]:
    return with_store(lambda store: store.proposals.listed(approved=True))


def examples() -> list[StoredExample]:
    return with_store(lambda store: store.knowledge.examples(BANK))


def test_a_proposal_waits_with_its_author_and_profile():
    number = propose()

    [found] = waiting()
    assert (found.id, found.connection, found.profile) == (number, BANK, "analyst")
    assert (found.question, found.sql, found.author) == (QUESTION, SQL, AGENT)
    assert found.approved_by is None
    assert approved() == []
    assert examples() == []


def test_a_question_asked_already_is_refused():
    _ = propose()

    with pytest.raises(ProposalError, match="proposed already") as caught:
        _ = propose(author="token:ba9876543210")

    assert caught.value.reason is Refusal.DUPLICATE


def test_a_question_that_is_an_example_is_refused():
    approve(propose())

    with pytest.raises(ProposalError, match="already an example") as caught:
        _ = propose(QUESTION, connection=BANK)

    assert caught.value.reason is Refusal.DUPLICATE


def test_an_author_has_a_bounded_number_waiting():
    _ = propose("one", waiting=2)
    second = propose("two", waiting=2)

    with pytest.raises(ProposalError, match="2 of your proposals") as caught:
        _ = propose("three", waiting=2)
    assert caught.value.reason is Refusal.QUEUE_FULL
    _ = propose("four", author="local:someone", waiting=2)

    approve(second, "two")
    _ = propose("three", waiting=2)


def test_approval_makes_it_an_example_that_names_its_proposal():
    number = propose()

    approve(number)

    [found] = approved()
    assert found.approved_by == "local:operator"
    assert found.approved_at is not None
    assert waiting() == []
    assert examples() == [
        StoredExample(QUESTION, SQL, "h", EMBEDDER.name, proposal=number),
    ]


def test_only_a_waiting_proposal_is_approved():
    number = propose()
    approve(number)

    with pytest.raises(ProposalError, match=f"no proposal {number} is waiting"):
        approve(number)
    with pytest.raises(ProposalError, match="no proposal 999 is waiting"):
        approve(999)


def test_approval_refuses_a_question_that_became_an_example():
    number = propose()
    with_store(
        lambda store: store.knowledge.update(
            BANK,
            examples=[(example(), EMBEDDER.query(QUESTION))],
        ),
    )

    with pytest.raises(ProposalError, match="already an example"):
        approve(number)

    assert [p.id for p in waiting()] == [number]
    assert [e.proposal for e in examples()] == [None]


def test_rejecting_drops_a_waiting_proposal():
    number = propose()

    dropped = with_store(lambda store: store.proposals.reject(number))

    assert dropped is not None
    assert dropped.question == QUESTION
    assert waiting() == []
    assert with_store(lambda store: store.proposals.reject(number)) is None


def test_rejecting_an_approved_one_takes_its_example_away():
    number = propose()
    approve(number)

    _ = with_store(lambda store: store.proposals.reject(number))

    assert approved() == []
    assert examples() == []


def test_the_queue_lists_by_connection():
    _ = propose("one")
    _ = propose("two", connection="cards")

    assert [p.question for p in waiting()] == ["one", "two"]
    assert [p.question for p in waiting("cards")] == ["two"]
