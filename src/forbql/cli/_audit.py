"""`forbql audit`: check the log's hash chain."""

from __future__ import annotations

from pathlib import Path  # ruff: ignore[typing-only-standard-library-import]
from typing import Annotated

import typer

from forbql.audit import verify_log

audit_app = typer.Typer(
    help="Check the audit log.",
    no_args_is_help=True,
    add_completion=False,
)


@audit_app.command()
def verify(path: Annotated[Path, typer.Argument(help="Audit log file.")]) -> None:
    """Check that no record was altered, removed or inserted; exit 1 if one was.

    Args:
        path: Path - Audit log file.

    Raises:
        typer.Exit: With code 1 when the chain is broken, 2 when the file is missing.

    """
    if not path.is_file():
        typer.echo(f"error: no audit log at {path}", err=True)
        raise typer.Exit(2)
    result = verify_log(path)
    if result.intact:
        typer.echo(f"{path}: intact; {result.records} record(s)")
        return
    held = f"{result.records} record(s) before it hold"
    typer.echo(f"{path}: broken at line {result.broken_at}: {result.reason} ({held})")
    raise typer.Exit(1)
