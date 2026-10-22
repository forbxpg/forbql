"""`forbql audit`: check the log's hash chain, and read it."""

from __future__ import annotations

from datetime import UTC
from pathlib import Path  # ruff: ignore[typing-only-standard-library-import]
from typing import TYPE_CHECKING, Annotated

import typer

from forbql.audit import Action, AuditRecord, read_log

from ._store import with_store

if TYPE_CHECKING:
    from forbql.audit import Verification

audit_app = typer.Typer(
    help="Check the audit log, and read it.",
    no_args_is_help=True,
    add_completion=False,
)

_SHOWN = 20
"""Records `show` prints when no limit is given."""


@audit_app.command()
def verify(
    path: Annotated[
        Path | None,
        typer.Argument(help="Audit log file; the store's chain when omitted."),
    ] = None,
) -> None:
    """Check that no record was altered, removed or inserted; exit 1 if one was.

    Args:
        path: Path | None - Audit log file; None for the chain in the store.

    Raises:
        typer.Exit: With code 1 when the chain is broken, 2 when the file is missing.

    """
    where, result, _records = _load(path)
    if result.intact:
        typer.echo(f"{where}: intact; {result.records} record(s)")
        return
    typer.echo(_broken(where, result))
    raise typer.Exit(1)


@audit_app.command()
def show(
    path: Annotated[
        Path | None,
        typer.Argument(help="Audit log file; the store's chain when omitted."),
    ] = None,
    *,
    limit: Annotated[
        int,
        typer.Option(min=1, help="Latest records to print."),
    ] = _SHOWN,
    action: Annotated[
        Action | None,
        typer.Option(help="Only this kind of call."),
    ] = None,
    denied: Annotated[
        bool,
        typer.Option("--denied", help="Only refused calls."),
    ] = False,
) -> None:
    """Print the latest records. What does not hold is not printed as history.

    Characters that do not print are escaped. A chain that breaks is named, the
    records before the break are printed, and the command exits 1.

    Args:
        path: Path | None - Audit log file; None for the chain in the store.
        limit: int - Latest records to print.
        action: Action | None - Only this kind of call.
        denied: bool - Only refused calls.

    Raises:
        typer.Exit: With code 1 when the chain is broken, 2 when the file is
            missing or the store is not configured.

    """
    where, result, records = _load(path)
    chosen = _chosen(records, limit=limit, action=action, denied=denied)
    if result.intact and not chosen:
        typer.echo("no audit records")
        return
    for record in chosen:
        typer.echo(_shown(record))
    if not result.intact:
        typer.echo(_broken(where, result))
        raise typer.Exit(1)


def _load(
    path: Path | None,
) -> tuple[str, Verification, tuple[AuditRecord, ...]]:
    """Read a file's chain, or the store's.

    Args:
        path: Path | None - The file; None for the store.

    Returns:
        tuple[str, Verification, tuple[AuditRecord, ...]] - Where it was read,
            how far it holds, and the records that do.

    Raises:
        typer.Exit: With code 2 when the file is missing.

    """
    if path is None:
        verification, records = with_store(lambda store: store.audit.read())
        return "the store's audit chain", verification, records
    if not path.is_file():
        typer.echo(f"error: no audit log at {path}", err=True)
        raise typer.Exit(2)
    verification, records = read_log(path)
    return str(path), verification, records


def _broken(where: str, result: Verification) -> str:
    """Name where a chain breaks.

    Args:
        where: str - The file, or the store.
        result: Verification - The check, which did not hold.

    Returns:
        str - The line to print before exiting 1.

    """
    held = f"{result.records} record(s) before it hold"
    return f"{where}: broken at line {result.broken_at}: {result.reason} ({held})"


def _chosen(
    records: tuple[AuditRecord, ...],
    *,
    limit: int,
    action: Action | None,
    denied: bool,
) -> tuple[AuditRecord, ...]:
    """Keep the latest records a caller asked to see.

    Args:
        records: tuple[AuditRecord, ...] - The chain, in order.
        limit: int - How many of the latest.
        action: Action | None - Only this kind of call.
        denied: bool - Only refused calls.

    Returns:
        tuple[AuditRecord, ...] - Those records, still in order.

    """
    matched = [
        record
        for record in records
        if (action is None or record.action is action)
        and (not denied or not record.allowed)
    ]
    return tuple(matched[-limit:])


def _shown(record: AuditRecord) -> str:
    """Write one record for a person to read.

    Args:
        record: AuditRecord - The record.

    Returns:
        str - Its header, and the text the caller sent.

    """
    when = record.at.astimezone(UTC).strftime("%Y-%m-%d %H:%MZ")
    outcome = "allowed" if record.allowed else "denied"
    if record.rules:
        outcome = f"{outcome} ({', '.join(record.rules)})"
    head = (
        f"{when}  {record.principal}  {record.connection}  {record.profile}  "
        f"{record.action}  {outcome}  {record.duration_ms}ms"
    )
    if record.error_class is not None:
        head = f"{head}  {record.error_class}"
    if record.truncated:
        head = f"{head}  truncated"
    body = _visible(record.sql).replace("\n", "\n  ")
    return f"{head}\n  {body}"


def _visible(text: str) -> str:
    """Escape the characters that do not print. Line breaks stay line breaks.

    Args:
        text: str - Text a caller sent.

    Returns:
        str - The text, every hidden character shown as its escape.

    """
    return "".join(
        character
        if character.isprintable() or character == "\n"
        else _escaped(character)
        for character in text
    )


def _escaped(character: str) -> str:
    """Write one character as its escape.

    Args:
        character: str - The character.

    Returns:
        str - Its `unicode_escape` form, without the quotes.

    """
    return character.encode("unicode_escape").decode()
