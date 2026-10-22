"""An append-only JSON Lines file of chained audit records."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from os import SEEK_END
from typing import TYPE_CHECKING, BinaryIO, override

from pydantic import ValidationError

from ._record import GENESIS, AuditRecord
from ._sink import AuditSink

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

if sys.platform == "win32":

    def _lock(_file: BinaryIO) -> None:  # pyright: ignore[reportRedeclaration]
        """Nothing: Windows has no flock, so one process at a time writes a file."""

else:
    from fcntl import LOCK_EX, flock

    def _lock(file: BinaryIO) -> None:
        """Hold the file exclusively until it is closed.

        Args:
            file: BinaryIO - The open log.

        """
        flock(file.fileno(), LOCK_EX)


_TAIL_CHUNK = 64 * 1024
"""Bytes read at a time while looking for the last record from the end."""


class AuditLog(AuditSink):
    """Appends records to a file, each carrying the previous record's hash.

    Every append locks the file and reads the last record from it, so sessions and
    processes sharing a file keep one chain. The lock is POSIX-only: on Windows one
    process at a time may write a file.

    Attributes:
        path: Path - The JSON Lines file; created on first append.

    """

    _path: Path

    def __init__(self, path: Path) -> None:
        self._path = path

    @override
    async def append(self, **fields: object) -> AuditRecord:
        """Write one record after the last one.

        Args:
            **fields: object - `AuditRecord` fields other than `at`, `previous`, `hash`.

        Returns:
            AuditRecord - The record as written.

        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a+b") as file:
            _lock(file)
            record = AuditRecord.chained(_last_hash(file), **fields)
            _ = file.write(record.model_dump_json().encode() + b"\n")
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


def read_log(path: Path) -> tuple[Verification, tuple[AuditRecord, ...]]:
    """Read a log and keep the records whose chain holds.

    Args:
        path: Path - The JSON Lines file.

    Returns:
        tuple[Verification, tuple[AuditRecord, ...]] - How far the chain holds,
            and those records, in order. A record after the break is left out:
            it is not history.

    """
    # Bytes, not text: a line that is not UTF-8 is a broken record, not a crash.
    with path.open("rb") as file:
        return read_chain(_parse(file))


def read_chain(
    records: Iterable[AuditRecord | None],
) -> tuple[Verification, tuple[AuditRecord, ...]]:
    """Check records in order and keep the ones that hold.

    Args:
        records: Iterable[AuditRecord | None] - The chain from its first record;
            None stands for something that is not a record.

    Returns:
        tuple[Verification, tuple[AuditRecord, ...]] - How far the chain holds,
            and those records, in order.

    """
    parsed = tuple(records)
    verification = verify_chain(parsed)
    held: list[AuditRecord] = []
    for record in parsed[: verification.records]:
        if record is None:
            break
        held.append(record)
    return verification, tuple(held)


def verify_log(path: Path) -> Verification:
    """Check that no record was altered, removed or inserted.

    Args:
        path: Path - The JSON Lines file.

    Returns:
        Verification - How many records hold, and where the chain breaks.

    """
    return read_log(path)[0]


def verify_chain(records: Iterable[AuditRecord | None]) -> Verification:
    """Check records in order: each unaltered, each after the one it names.

    Args:
        records: Iterable[AuditRecord | None] - The chain from its first record;
            None stands for something that is not a record.

    Returns:
        Verification - How many records hold, and where the chain breaks.

    """
    previous = GENESIS
    count = 0
    for number, record in enumerate(records, start=1):
        if record is None:
            return Verification(count, number, "not an audit record")

        if record.previous != previous:
            reason = "chain broken: a record is missing or moved"
            return Verification(count, number, reason)

        if record.hash != record.expected_hash():
            reason = "record altered after it was written"
            return Verification(count, number, reason)

        previous = record.hash
        count += 1

    return Verification(count)


def _parse(lines: Iterable[bytes]) -> Iterator[AuditRecord | None]:
    """Read JSON Lines as records; a line that is not one reads as None.

    Args:
        lines: Iterable[bytes] - The file's lines.

    Yields:
        AuditRecord | None - One per line.

    """
    for line in lines:
        try:
            yield AuditRecord.model_validate_json(line)
        except ValidationError:
            yield None


def _last_hash(file: BinaryIO) -> str:
    """Read the hash of the file's last record, scanning back from the end.

    Args:
        file: BinaryIO - The log, open for reading.

    Returns:
        str - The last record's hash; `GENESIS` for an empty log.

    """
    position = file.seek(0, SEEK_END)
    tail = b""
    while position > 0:
        step = min(_TAIL_CHUNK, position)
        position -= step
        _ = file.seek(position)
        tail = file.read(step) + tail
        _, newline, last = tail.rstrip(b"\n").rpartition(b"\n")
        if newline or position == 0:
            return AuditRecord.model_validate_json(last).hash if last else GENESIS
    return GENESIS
