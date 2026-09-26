"""The workspace's audit chain in the store: appends only, one at a time."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast, override

from pydantic import ValidationError
from sqlalchemy import insert, select, update

from forbql.audit import AuditRecord, AuditSink, Verification, verify_chain

from ._errors import StoreError
from ._tables import audit_heads, audit_records

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncEngine


_FIELDS = frozenset(AuditRecord.model_fields)
"""A row's columns that are the record's; `workspace_id` and `seq` place it."""


class StoreAuditLog(AuditSink):
    """Appends a workspace's records to the store, each after the chain's head.

    The runtime role may insert records and move the head, never change a record:
    the migrations grant nothing more.

    Args:
        engine: AsyncEngine - The store.
        workspace_id: UUID - Whose chain.

    """

    _engine: AsyncEngine
    _workspace_id: UUID

    def __init__(self, engine: AsyncEngine, workspace_id: UUID) -> None:
        self._engine = engine
        self._workspace_id = workspace_id

    @override
    async def append(self, **fields: object) -> AuditRecord:
        """Write one record after the head, holding the head until it is written.

        Args:
            **fields: object - `AuditRecord` fields other than `at`, `previous`, `hash`.

        Returns:
            AuditRecord - The record as written.

        Raises:
            StoreError: If the workspace has no chain.

        """
        mine = audit_heads.c.workspace_id == self._workspace_id
        async with self._engine.begin() as connection:
            # FOR UPDATE: a second writer waits here, so no two records share a head.
            query = select(audit_heads.c.seq, audit_heads.c.hash).where(mine)
            head = (await connection.execute(query.with_for_update())).one_or_none()
            if head is None:
                msg = "the workspace has no audit chain in the store"
                raise StoreError(msg)
            seq, previous = cast("tuple[int, str]", head)
            record = AuditRecord.chained(previous, **fields)
            _ = await connection.execute(
                insert(audit_records).values(
                    workspace_id=self._workspace_id,
                    seq=seq + 1,
                    **record.model_dump(),
                ),
            )
            _ = await connection.execute(
                update(audit_heads).where(mine).values(seq=seq + 1, hash=record.hash),
            )
        return record

    async def verify(self) -> Verification:
        """Check the workspace's chain from its first record.

        Returns:
            Verification - How many records hold, and where the chain breaks.

        """
        # ponytail: reads the whole chain into memory; stream it once logs grow large.
        query = (
            select(audit_records)
            .where(audit_records.c.workspace_id == self._workspace_id)
            .order_by(audit_records.c.seq)
        )
        async with self._engine.connect() as connection:
            rows = (await connection.execute(query)).mappings().all()
        return verify_chain(_record(dict(row)) for row in rows)


def _record(row: dict[str, object]) -> AuditRecord | None:
    """Read a row as a record; a row that is not one reads as None.

    Args:
        row: dict[str, object] - The row.

    Returns:
        AuditRecord | None - The record.

    """
    fields = {name: value for name, value in row.items() if name in _FIELDS}
    try:
        return AuditRecord.model_validate(fields)
    except ValidationError:
        return None
