"""An append-only JSON Lines file of chained audit records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import ValidationError

from ._record import GENESIS, AuditRecord

if TYPE_CHECKING:
    from pathlib import Path


class AuditLog:
    """Appends records to a file, each carrying the previous record's hash.

    One writer per file: the store serialises concurrent writers.

    Attributes:
        path: Path - The JSON Lines file; created on first append.
        last: str | None - The hash of the last record; None for the first.

    """

    _path: Path
    _last: str | None

    def __init__(self, path: Path) -> None:
        self._path = path
        self._last = None

    def append(self, **fields: object) -> AuditRecord:
        """Write one record after the last one.

        Args:
            **fields: object - `AuditRecord` fields other than `at`, `previous`, `hash`.

        Returns:
            AuditRecord - The record as written.

        """
        previous = self._last if self._last is not None else _last_hash(self._path)
        draft = AuditRecord.model_validate(
            {
                **fields,
                "at": datetime.now(UTC),
                "previous": previous,
                "hash": "",
            },
        )
        record = draft.model_copy(update={"hash": draft.expected_hash()})
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as file:
            _ = file.write(record.model_dump_json() + "\n")
        self._last = record.hash
        return record


@dataclass(frozen=True, slots=True)
class Verification:
    """Outcome of checking a log.

    Attributes:
        records: int - Records read before stopping.
        broken_at: int | None - Line number of the first bad record; None if intact.
        reason: str | None - What was wrong there.

    """

    records: int
    broken_at: int | None = None
    reason: str | None = None

    @property
    def intact(self) -> bool:
        """Whether every record is unaltered and in its place."""
        return self.broken_at is None


def verify_log(path: Path) -> Verification:
    """Check that no record was altered, removed or inserted.

    Args:
        path: Path - The JSON Lines file.

    Returns:
        Verification - How many records hold, and where the chain breaks.

    """
    previous = GENESIS
    records = 0
    with path.open(encoding="utf-8") as file:
        for number, line in enumerate(file, start=1):
            try:
                record = AuditRecord.model_validate_json(line)
            except ValidationError:
                return Verification(records, number, "not an audit record")

            if record.previous != previous:
                reason = "chain broken: a record is missing or moved"
                return Verification(records, number, reason)

            if record.hash != record.expected_hash():
                reason = "record altered after it was written"
                return Verification(records, number, reason)

            previous = record.hash
            records += 1

    return Verification(records)


def _last_hash(path: Path) -> str:
    if not path.exists():
        return GENESIS
    last = GENESIS
    with path.open(encoding="utf-8") as file:
        for line in file:
            if line.strip():
                last = AuditRecord.model_validate_json(line).hash
    return last
