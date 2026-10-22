from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self
from uuid import uuid4

from forbql.audit import GENESIS, Action, AuditRecord, Verification
from forbql.store import StoreAuditLog

if TYPE_CHECKING:
    from collections.abc import Sequence


def fields(sql: str) -> dict[str, object]:
    return {
        "principal": "local",
        "connection": "bank",
        "profile": "analyst",
        "action": Action.SQL_RUN,
        "policy_hash": "sha256:x",
        "sql": sql,
        "executed_sql": sql,
        "allowed": True,
        "rules": (),
        "rows": 1,
        "size": 1,
        "truncated": False,
        "duration_ms": 1,
        "error_class": None,
        "error_detail": None,
    }


def chain(statements: Sequence[str]) -> list[AuditRecord]:
    previous = GENESIS
    records: list[AuditRecord] = []
    for sql in statements:
        record = AuditRecord.chained(previous, **fields(sql))
        records.append(record)
        previous = record.hash
    return records


def row(record: AuditRecord, seq: int) -> dict[str, object]:
    return {"seq": seq, **record.model_dump()}


class _Rows:
    _rows: list[dict[str, object]]

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> _Rows:
        return self

    def all(self) -> list[dict[str, object]]:
        return self._rows


class _Head:
    _head: tuple[int, str] | None

    def __init__(self, head: tuple[int, str] | None) -> None:
        self._head = head

    def one_or_none(self) -> tuple[int, str] | None:
        return self._head


class _Connection:
    _rows: list[dict[str, object]]
    _head: tuple[int, str] | None

    def __init__(
        self,
        rows: list[dict[str, object]],
        head: tuple[int, str] | None,
    ) -> None:
        self._rows = rows
        self._head = head

    async def execute(self, query: object) -> _Rows | _Head:
        if "audit_heads" in str(query):
            return _Head(self._head)
        return _Rows(self._rows)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _Engine:
    _rows: list[dict[str, object]]
    _head: tuple[int, str] | None

    def __init__(
        self,
        rows: list[dict[str, object]],
        head: tuple[int, str] | None,
    ) -> None:
        self._rows = rows
        self._head = head

    def connect(self) -> _Connection:
        return _Connection(self._rows, self._head)


def verify(rows: list[dict[str, object]], head: tuple[int, str] | None):
    # The engine stands in for the two reads verify has to make.
    log = StoreAuditLog(_Engine(rows, head), uuid4())  # pyright: ignore[reportArgumentType]
    return asyncio.run(log.verify())


def test_a_missing_tail_does_not_match_the_head():
    records = chain(["SELECT 1", "SELECT 2", "SELECT 3"])
    kept = [row(record, seq) for seq, record in enumerate(records[:2], start=1)]

    result = verify(kept, (3, records[2].hash))

    assert result == Verification(2, 3, "head does not match the chain")


def test_the_head_sequence_must_name_the_last_row():
    records = chain(["SELECT 1", "SELECT 2", "SELECT 3"])
    rows = [row(record, seq) for seq, record in enumerate(records, start=1)]

    # The hash is the last row's, so only a sequence comparison can fail this.
    result = verify(rows, (99, records[-1].hash))

    assert result == Verification(3, 4, "head does not match the chain")


def test_records_without_a_head_row_are_not_intact():
    records = chain(["SELECT 1"])

    result = verify([row(records[0], 1)], None)

    assert result == Verification(1, 2, "audit head is missing")


def test_a_chain_that_ends_at_its_head_is_intact():
    records = chain(["SELECT 1", "SELECT 2", "SELECT 3"])
    rows = [row(record, seq) for seq, record in enumerate(records, start=1)]

    assert verify(rows, (3, records[-1].hash)) == Verification(records=3)


def test_an_empty_chain_at_genesis_is_intact():
    assert verify([], (0, GENESIS)) == Verification(records=0)


def test_an_altered_row_is_found_before_the_head():
    records = chain(["SELECT 1", "SELECT 2", "SELECT 3"])
    rows = [row(record, seq) for seq, record in enumerate(records, start=1)]
    rows[1]["rows"] = 999

    result = verify(rows, (3, records[-1].hash))

    assert result == Verification(1, 2, "record altered after it was written")


def test_moving_the_head_to_the_remaining_end_still_verifies():
    # Rewriting both the rows and the head is not something this check can see.
    records = chain(["SELECT 1", "SELECT 2", "SELECT 3"])
    kept = [row(record, seq) for seq, record in enumerate(records[:2], start=1)]

    assert verify(kept, (2, records[1].hash)) == Verification(records=2)
