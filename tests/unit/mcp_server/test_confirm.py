from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass

import pytest
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import AcceptedElicitation, DeclinedElicitation
from mcp.types import ElicitResult, InputRequiredResult

from forbql.mcp import ASK, confirm

QUERY = "SELECT * FROM transactions"
DIGEST = hashlib.sha256(QUERY.encode()).hexdigest()


@dataclass
class Request:
    protocol_version: str


@dataclass
class Fake:
    input_responses: dict[str, object] | None = None
    request_state: str | None = None
    request_context: Request | None = None
    answer: object = None

    async def elicit(self, message: str, response_type: type) -> object:
        assert response_type is bool
        assert message == "Run it?"
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def ask(ctx: Fake) -> bool | InputRequiredResult:
    return asyncio.run(confirm(ctx, message="Run it?", query=QUERY))  # pyright: ignore[reportArgumentType]


def test_a_new_protocol_gets_the_question_tied_to_the_query():
    asked = ask(Fake(request_context=Request("2026-07-28")))

    assert isinstance(asked, InputRequiredResult)
    assert asked.request_state == DIGEST
    assert asked.input_requests is not None
    assert list(asked.input_requests) == [ASK]


@pytest.mark.parametrize(
    ("answer", "state", "expected"),
    [
        (ElicitResult(action="accept", content={"run": True}), DIGEST, True),
        (ElicitResult(action="accept", content={"run": False}), DIGEST, False),
        (ElicitResult(action="decline"), DIGEST, False),
        (ElicitResult(action="accept", content={"run": True}), "another query", False),
    ],
)
def test_the_answer_counts_only_for_the_query_it_was_asked_about(
    answer: ElicitResult,
    state: str,
    *,
    expected: bool,
):
    ctx = Fake(input_responses={ASK: answer}, request_state=state)

    assert ask(ctx) is expected


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (AcceptedElicitation(data=True), True),
        (AcceptedElicitation(data=False), False),
        (DeclinedElicitation(), False),
        (ToolError("the client cannot ask"), False),
    ],
)
def test_an_older_protocol_asks_and_waits(answer: object, *, expected: bool):
    ctx = Fake(request_context=Request("2025-11-25"), answer=answer)

    assert ask(ctx) is expected
