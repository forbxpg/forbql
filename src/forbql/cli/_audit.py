"""`forbql audit`: check the log's hash chain."""

from __future__ import annotations

from pathlib import Path  # ruff: ignore[typing-only-standard-library-import]
from typing import Annotated

import typer

from forbql.audit import verify_log

from ._store import with_store

audit_app = typer.Typer(
    help="Check the audit log.",
    no_args_is_help=True,
    add_completion=False,
)


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
    if path is None:
        where = "the store's audit chain"
        result = with_store(lambda store: store.audit.verify())
    elif not path.is_file():
        typer.echo(f"error: no audit log at {path}", err=True)
        raise typer.Exit(2)
    else:
        where = str(path)
        result = verify_log(path)
    if result.intact:
        typer.echo(f"{where}: intact; {result.records} record(s)")
        return
    held = f"{result.records} record(s) before it hold"
    typer.echo(f"{where}: broken at line {result.broken_at}: {result.reason} ({held})")
    raise typer.Exit(1)
