"""Examples agents propose: a queue the operator approves from, or rejects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from itertools import starmap
from typing import TYPE_CHECKING, cast

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from ._errors import StoreError
from ._tables import example_proposals, examples

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncEngine

    from ._knowledge import StoredExample


class Refusal(StrEnum):
    """Why the queue refuses; the audit records it."""

    DUPLICATE = "duplicate"
    QUEUE_FULL = "queue_full"
    NOT_WAITING = "not_waiting"


class ProposalError(StoreError):
    """The queue refuses a proposal or a decision on one.

    Args:
        reason: Refusal - Why, for the audit record.
        message: str - What the proposer or the operator reads.

    """

    reason: Refusal

    def __init__(self, reason: Refusal, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class StoredProposal:
    """A proposed example, waiting or approved.

    Attributes:
        id: int - Its number, which the operator names it by.
        connection: str - Connection name.
        profile: str - The proposer's profile.
        question: str - The question.
        sql: str - The query.
        author: str - Who proposed it: `token:<id>` or `local:<user>`.
        proposed_at: datetime - When.
        approved_by: str | None - Who approved it; None while it waits.
        approved_at: datetime | None - When.

    """

    id: int
    connection: str
    profile: str
    question: str
    sql: str
    author: str
    proposed_at: datetime
    approved_by: str | None
    approved_at: datetime | None


_COLUMNS = (
    example_proposals.c.id,
    example_proposals.c.connection,
    example_proposals.c.profile,
    example_proposals.c.question,
    example_proposals.c.sql,
    example_proposals.c.author,
    example_proposals.c.proposed_at,
    example_proposals.c.approved_by,
    example_proposals.c.approved_at,
)

type _Row = tuple[
    int,
    str,
    str,
    str,
    str,
    str,
    datetime,
    str | None,
    datetime | None,
]


class StoreProposals:
    """A workspace's proposed examples.

    Args:
        engine: AsyncEngine - The store.
        workspace_id: UUID - Whose queue.

    """

    _engine: AsyncEngine
    _workspace_id: UUID

    def __init__(self, engine: AsyncEngine, workspace_id: UUID) -> None:
        self._engine = engine
        self._workspace_id = workspace_id

    async def add(  # ruff: ignore[too-many-arguments] - the proposal and its bound
        self,
        connection: str,
        *,
        profile: str,
        question: str,
        sql: str,
        author: str,
        waiting: int,
    ) -> int:
        """Queue an example, unless its question is taken or the author has enough.

        Args:
            connection: str - Connection name.
            profile: str - The proposer's profile.
            question: str - The question.
            sql: str - The query.
            author: str - Who proposes it.
            waiting: int - Proposals an author may have waiting at once.

        Returns:
            int - The proposal's number.

        Raises:
            ProposalError: If the question is an example or proposed already, or
                the author has `waiting` proposals waiting.

        """
        p = example_proposals.c
        known = select(examples.c.question).where(
            examples.c.workspace_id == self._workspace_id,
            examples.c.connection == connection,
            examples.c.question == question,
        )
        queued = select(func.count()).where(
            p.workspace_id == self._workspace_id,
            p.connection == connection,
            p.author == author,
            p.approved_at.is_(None),
        )
        statement = (
            insert(example_proposals)
            .values(
                workspace_id=self._workspace_id,
                connection=connection,
                profile=profile,
                question=question,
                sql=sql,
                author=author,
            )
            .returning(p.id)
        )
        async with self._engine.begin() as db:
            if await db.scalar(known) is not None:
                msg = f"there is already an example for {question!r}: search for it"
                raise ProposalError(Refusal.DUPLICATE, msg)
            count = cast("int", await db.scalar(queued))
            # Two proposals racing past the count may both land: one over is harmless.
            if count >= waiting:
                msg = (
                    f"{count} of your proposals are waiting for review, the most "
                    "allowed: ask the operator to review them"
                )
                raise ProposalError(Refusal.QUEUE_FULL, msg)
            try:
                return cast("int", await db.scalar(statement))
            except IntegrityError as error:
                msg = f"{question!r} is proposed already and waits for review"
                raise ProposalError(Refusal.DUPLICATE, msg) from error

    async def listed(
        self,
        *,
        connection: str | None = None,
        approved: bool = False,
    ) -> list[StoredProposal]:
        """List proposals waiting for review, or approved ones.

        Args:
            connection: str | None - Only this connection's; None for every one.
            approved: bool - Approved ones instead of those waiting.

        Returns:
            list[StoredProposal] - Oldest first.

        """
        p = example_proposals.c
        query = (
            select(*_COLUMNS)
            .where(
                p.workspace_id == self._workspace_id,
                p.approved_at.is_not(None) if approved else p.approved_at.is_(None),
            )
            .order_by(p.id)
        )
        if connection is not None:
            query = query.where(p.connection == connection)
        async with self._engine.connect() as db:
            rows = cast("Sequence[_Row]", (await db.execute(query)).all())
        return list(starmap(StoredProposal, rows))

    async def get(self, number: int) -> StoredProposal | None:
        """Read one proposal.

        Args:
            number: int - Its number.

        Returns:
            StoredProposal | None - The proposal; None if there is no such one.

        """
        query = select(*_COLUMNS).where(
            example_proposals.c.workspace_id == self._workspace_id,
            example_proposals.c.id == number,
        )
        async with self._engine.connect() as db:
            row = cast("_Row | None", (await db.execute(query)).one_or_none())
        return None if row is None else StoredProposal(*row)

    async def approve(
        self,
        number: int,
        *,
        by: str,
        example: StoredExample,
        vector: Sequence[float],
    ) -> None:
        """Mark a waiting proposal approved and add it to the examples, at once.

        Args:
            number: int - The proposal's number.
            by: str - Who approves it.
            example: StoredExample - The example as search keeps it.
            vector: Sequence[float] - Its embedding.

        Raises:
            ProposalError: If it is not waiting, or its question became an example
                in the meantime; nothing changes then.

        """
        p = example_proposals.c
        mark = (
            update(example_proposals)
            .where(
                p.workspace_id == self._workspace_id,
                p.id == number,
                p.approved_at.is_(None),
            )
            .values(approved_by=by, approved_at=func.now())
            .returning(p.connection)
        )
        row = {
            "workspace_id": self._workspace_id,
            "question": example.question,
            "sql": example.sql,
            "body_hash": example.body_hash,
            "model": example.model,
            "embedding": list(vector),
            "proposal_id": number,
        }
        async with self._engine.begin() as db:
            connection = cast("str | None", await db.scalar(mark))
            if connection is None:
                msg = f"no proposal {number} is waiting for review"
                raise ProposalError(Refusal.NOT_WAITING, msg)
            try:
                _ = await db.execute(
                    insert(examples).values(connection=connection, **row),
                )
            except IntegrityError as error:
                msg = (
                    f"there is already an example for {example.question!r}: reject "
                    f"proposal {number}"
                )
                raise ProposalError(Refusal.DUPLICATE, msg) from error

    async def reject(self, number: int) -> StoredProposal | None:
        """Drop a proposal; an approved one leaves the examples with it.

        Args:
            number: int - Its number.

        Returns:
            StoredProposal | None - What was dropped; None if there was nothing.

        """
        statement = (
            delete(example_proposals)
            .where(
                example_proposals.c.workspace_id == self._workspace_id,
                example_proposals.c.id == number,
            )
            .returning(*_COLUMNS)
        )
        async with self._engine.begin() as db:
            row = cast("_Row | None", (await db.execute(statement)).one_or_none())
        return None if row is None else StoredProposal(*row)
