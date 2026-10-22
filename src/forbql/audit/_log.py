"""An append-only JSON Lines file of chained audit records."""

from __future__ import annotations

import os
import sys
from contextlib import suppress
from dataclasses import dataclass
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

_HEAD_MISMATCH = "head does not match the chain"
"""Why verification failed when the chain does not end where its head says."""

_HEAD_MISSING = "audit head is missing"
"""Why verification failed when a log has records and no sibling head."""

_OWNER_ONLY = 0o600
"""Mode of the log and its head: the owner reads and writes, and nobody else."""


class AuditLog(AuditSink):
    """Appends records to a file, each carrying the previous record's hash.

    Every append locks the file and reads the last record from it, so sessions and
    processes sharing a file keep one chain. The lock is POSIX-only: on Windows one
    process at a time may write a file. Each append also publishes a sibling head
    file, `<log name>.head`, holding the record count and the last hash, so a
    removed tail does not verify. A log that already has records and no head
    does not verify either. The log is created and opened with mode 0o600.

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
        with _open_log(self._path) as file:
            _lock(file)
            last = _last_hash(file)
            count = _records_already(file, self._path, last)
            record = AuditRecord.chained(last, **fields)
            _ = file.write(record.model_dump_json().encode() + b"\n")
            file.flush()
            _ = os.fsync(file.fileno())
            _write_head(self._path, record.hash, count + 1)
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

    The sibling head names the last hash and the record count. A chain that ends
    somewhere else is not intact, and neither is a populated log whose head is
    gone. An empty log may have no head. A writer who can rewrite both the log
    and the head can still forge history; the head is what makes a missing tail
    visible.

    Args:
        path: Path - The JSON Lines file.

    Returns:
        Verification - How many records hold, and where the chain breaks.

    """
    # Bytes, not text: a line that is not UTF-8 is a broken record, not a crash.
    # The lock is the same one append holds, so the log and its head are one pair.
    with path.open("rb") as file:
        _lock(file)
        # Opening the log tightens it. A file we cannot chmod is still checked.
        with suppress(OSError):
            _owner_only(file.fileno())
        head = _read_head(path)
        result = verify_chain(_parse(file), head=head)
    if head is None and result.intact and result.records:
        return Verification(result.records, result.records + 1, _HEAD_MISSING)
    return result


def verify_chain(
    records: Iterable[AuditRecord | None],
    *,
    head: tuple[int, str] | None = None,
) -> Verification:
    """Check records in order: each unaltered, each after the one it names.

    Args:
        records: Iterable[AuditRecord | None] - The chain from its first record;
            None stands for something that is not a record.
        head: tuple[int, str] | None - Record count and last hash from the log's
            head. None skips that comparison; a different length or last hash
            does not verify.

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

    if head is None or (head[0] == count and head[1] == previous):
        return Verification(count)
    if head[0] == count:
        held = count - 1 if count else 0
        return Verification(held, count or 1, _HEAD_MISMATCH)
    return Verification(count, count + 1, _HEAD_MISMATCH)


def _head_path(path: Path) -> Path:
    """Path of the head published beside the log.

    Args:
        path: Path - The JSON Lines file.

    Returns:
        Path - `<log name>.head` in the same directory.

    """
    return path.with_name(path.name + ".head")


def _write_head(path: Path, digest: str, records: int) -> None:
    """Publish the record count and last hash beside the log.

    The temporary file is replaced into place, so a reader sees the previous
    head or the new one and never a partial write.

    Args:
        path: Path - The JSON Lines file.
        digest: str - Hash of the record just written.
        records: int - How many records the log holds, including that one.

    Raises:
        OSError: If the head cannot be written.

    """
    destination = _head_path(path)
    temporary = destination.with_name(f".{destination.name}.tmp")
    payload = f"{records}\n{digest}\n".encode()
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        _OWNER_ONLY,
    )
    try:
        _owner_only(descriptor)
    except OSError:
        os.close(descriptor)
        raise
    with os.fdopen(descriptor, "wb") as opened:
        _ = opened.write(payload)
        opened.flush()
        _ = os.fsync(opened.fileno())
    _ = temporary.replace(destination)


def _read_head(path: Path) -> tuple[int, str] | None:
    """Read the head beside the log.

    Args:
        path: Path - The JSON Lines file.

    Returns:
        tuple[int, str] | None - Record count and last hash. None when no head
            file exists. `(-1, "")` when a file is there but is not that pair.

    """
    head = _head_path(path)
    if not head.is_file():
        return None
    try:
        text = head.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return (-1, "")
    count_text, separator, digest = text.strip().partition("\n")
    if not separator or "\n" in digest:
        return (-1, "")
    if not count_text.isascii() or not count_text.isdecimal():
        return (-1, "")
    if not digest or any(character.isspace() for character in digest):
        return (-1, "")
    return int(count_text), digest


def _records_already(file: BinaryIO, path: Path, last: str) -> int:
    """How many records the log already holds.

    Args:
        file: BinaryIO - The open log.
        path: Path - The JSON Lines file.
        last: str - Hash of the last record; GENESIS when the log is empty.

    Returns:
        int - The count. The head's count is used when its hash is `last`.

    """
    if last == GENESIS:
        return 0
    head = _read_head(path)
    if head is not None and head[1] == last:
        return head[0]
    return _count_records(file)


def _count_records(file: BinaryIO) -> int:
    """Count records by their lines.

    Args:
        file: BinaryIO - The open log.

    Returns:
        int - Lines that are not empty.

    """
    _ = file.seek(0)
    return sum(1 for line in file if line.strip())


def _open_log(path: Path) -> BinaryIO:
    """Open the log for reading and appending, owner-readable only.

    The file is created with mode 0o600, and an existing file is set to that
    mode before anything is written. Group and other bits are cleared.

    Args:
        path: Path - The JSON Lines file.

    Returns:
        BinaryIO - The open log. The caller closes it.

    Raises:
        OSError: If the log cannot be opened or its mode cannot be set.

    """
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, _OWNER_ONLY)
    try:
        _owner_only(descriptor)
    except OSError:
        os.close(descriptor)
        raise
    return os.fdopen(descriptor, "a+b")


def _owner_only(descriptor: int) -> None:
    """Set an open file to mode 0o600 where the platform can.

    Args:
        descriptor: int - A file the caller has open.

    """
    if sys.platform == "win32":
        return
    os.fchmod(descriptor, _OWNER_ONLY)


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
    position = file.seek(0, os.SEEK_END)
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
