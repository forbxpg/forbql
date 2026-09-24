"""`forbql run`: one query through the whole pipeline, audited."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path  # ruff: ignore[typing-only-standard-library-import]
from typing import TYPE_CHECKING, Annotated

import typer

from forbql.policy import PolicyError, UnknownProfileError
from forbql.session import DEFAULT_AUDIT_LOG, SessionError, connect

if TYPE_CHECKING:
    from collections.abc import Sequence

    from forbql.session import RunResult

_MAX_WIDTH = 40


def run(  # ruff: ignore[too-many-arguments] - one parameter per command-line option
    sql: Annotated[
        str,
        typer.Argument(help="The query; '-' reads it from standard input."),
    ],
    *,
    policy: Annotated[
        Path,
        typer.Option(help="Policy file.", envvar="FORBQL_POLICY"),
    ],
    connection: Annotated[str, typer.Option(help="Connection in the policy.")],
    profile: Annotated[str, typer.Option(help="Profile of the connection.")],
    dsn: Annotated[
        str | None,
        typer.Option(help="DSN; defaults to FORBQL_DSN_<CONNECTION>."),
    ] = None,
    audit_log: Annotated[
        Path | None,
        typer.Option(
            help="JSON Lines file every call is recorded in.",
            envvar="FORBQL_AUDIT_LOG",
            show_default=str(DEFAULT_AUDIT_LOG),
        ),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print the result as JSON."),
    ] = False,
) -> None:
    """Check a query, run it read-only, mask it, audit it; exit 0 if rows came back.

    Args:
        sql: str - The query, or '-' for standard input.
        policy: Path - Policy file.
        connection: str - Connection in the policy.
        profile: str - Profile of the connection.
        dsn: str | None - DSN for the connection.
        audit_log: Path | None - Audit log file.
        as_json: bool - Print JSON instead of a table.

    Raises:
        typer.Exit: Always; 0 when rows came back, 1 when rejected or the database
            failed, 2 when the session could not open.

    """
    text = sys.stdin.read() if sql == "-" else sql

    async def go() -> tuple[RunResult, tuple[str, ...]]:
        async with connect(
            policy,
            connection=connection,
            profile=profile,
            dsn=dsn,
            audit_log=audit_log,
        ) as session:
            return await session.run(text), session.warnings

    try:
        result, warnings = asyncio.run(go())
    except (PolicyError, UnknownProfileError, SessionError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error
    for warning in warnings:
        typer.echo(f"warning: {warning}", err=True)
    typer.echo(to_json(result) if as_json else render(result))
    raise typer.Exit(0 if result.ok else 1)


def render(result: RunResult) -> str:
    """Format a result as a text table for a person.

    Args:
        result: RunResult - The result.

    Returns:
        str - Text lines.

    """
    verdict = result.verdict
    if not verdict.allowed:
        return "\n".join(
            ["rejected"] + [f"  {v.rule}: {v.message}" for v in verdict.violations],
        )
    if result.error is not None:
        return f"database error: {result.error}\n  hint: {result.hint}"
    cells = [[_cell(value) for value in row] for row in result.rows]
    widths = [
        max([len(name), *(len(row[i]) for row in cells)])
        for i, name in enumerate(result.columns)
    ]
    lines = [_line(result.columns, widths), "  ".join("-" * width for width in widths)]
    lines += [_line(row, widths) for row in cells]
    footer = f"({len(result.rows)} rows{', truncated' if result.truncated else ''})"
    return "\n".join([*lines, footer])


def to_json(result: RunResult) -> str:
    """Format a result as JSON for a program.

    Args:
        result: RunResult - The result.

    Returns:
        str - A JSON document.

    """
    return json.dumps(
        {
            "verdict": result.verdict.model_dump(mode="json"),
            "columns": list(result.columns),
            "rows": [list(row) for row in result.rows],
            "truncated": result.truncated,
            "error": result.error,
            "hint": result.hint,
        },
        default=str,
        ensure_ascii=False,
        indent=2,
    )


def _line(cells: Sequence[str], widths: Sequence[int]) -> str:
    return "  ".join(
        cell.ljust(width) for cell, width in zip(cells, widths, strict=True)
    )


def _cell(value: object) -> str:
    text = "NULL" if value is None else str(value)
    return text if len(text) <= _MAX_WIDTH else text[: _MAX_WIDTH - 1] + "…"
