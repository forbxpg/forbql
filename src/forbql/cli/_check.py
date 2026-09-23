"""`forbql check`: a verdict for one query, without touching any database."""

from __future__ import annotations

import sys
from pathlib import Path  # ruff: ignore[typing-only-standard-library-import]
from typing import TYPE_CHECKING, Annotated

import typer
from pydantic import ValidationError

from forbql.firewall import Firewall, SchemaSnapshot, check_structure
from forbql.policy import Engine, PolicyError, UnknownProfileError

if TYPE_CHECKING:
    from forbql.firewall import Verdict


def check(  # ruff: ignore[too-many-arguments] - one parameter per command-line option
    sql: Annotated[
        str,
        typer.Argument(help="The query; '-' reads it from standard input."),
    ],
    *,
    dialect: Annotated[
        Engine | None,
        typer.Option(help="Engine to check against when there is no policy."),
    ] = None,
    policy: Annotated[
        Path | None,
        typer.Option(help="Policy file.", envvar="FORBQL_POLICY"),
    ] = None,
    connection: Annotated[
        str | None,
        typer.Option(help="Connection in the policy."),
    ] = None,
    profile: Annotated[
        str | None,
        typer.Option(help="Profile of the connection."),
    ] = None,
    schema: Annotated[
        Path | None,
        typer.Option(help="Schema snapshot (JSON) of the connection."),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Print the verdict as JSON."),
    ] = False,
) -> None:
    """Check a query and print the verdict; exit 0 if allowed, 1 if rejected.

    Without --policy only structural and dialect rules apply. With --policy but without
    --schema, tables, columns and PII are not checked; the verdict says so.

    Args:
        sql: str - The query, or '-' for standard input.
        dialect: Engine | None - Engine for a check without a policy.
        policy: Path | None - Policy file.
        connection: str | None - Connection in the policy.
        profile: str | None - Profile of the connection.
        schema: Path | None - Schema snapshot of the connection.
        as_json: bool - Print JSON instead of text.

    Raises:
        typer.Exit: Always; code 0 when allowed, 1 when rejected, 2 on bad input.

    """
    text = sys.stdin.read() if sql == "-" else sql
    try:
        verdict = _verdict(
            text,
            dialect=dialect,
            policy=policy,
            connection=connection,
            profile=profile,
            schema=schema,
        )
    except (PolicyError, UnknownProfileError, ValidationError, OSError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error
    typer.echo(verdict.model_dump_json(indent=2) if as_json else render(verdict))
    raise typer.Exit(0 if verdict.allowed else 1)


def _verdict(  # ruff: ignore[too-many-arguments] - mirrors the command's options
    sql: str,
    *,
    dialect: Engine | None,
    policy: Path | None,
    connection: str | None,
    profile: str | None,
    schema: Path | None,
) -> Verdict:
    """Pick the kind of check the options ask for and run it.

    Args:
        sql: str - The query.
        dialect: Engine | None - Engine for a check without a policy.
        policy: Path | None - Policy file.
        connection: str | None - Connection in the policy.
        profile: str | None - Profile of the connection.
        schema: Path | None - Schema snapshot of the connection.

    Returns:
        Verdict - The verdict.

    Raises:
        typer.BadParameter: If the options do not form a valid combination.

    """
    if policy is None:
        if dialect is None:
            msg = "give --dialect, or --policy with --connection and --profile"
            raise typer.BadParameter(msg)
        if connection or profile or schema:
            msg = "--connection, --profile and --schema need --policy"
            raise typer.BadParameter(msg)
        return check_structure(sql, dialect)
    if dialect is not None:
        msg = "the policy sets the engine; drop --dialect"
        raise typer.BadParameter(msg)
    if connection is None or profile is None:
        msg = "--policy needs --connection and --profile"
        raise typer.BadParameter(msg)
    snapshots = None
    if schema is not None:
        snapshot = SchemaSnapshot.model_validate_json(
            schema.read_text(encoding="utf-8"),
        )
        snapshots = {connection: snapshot}
    firewall = Firewall.from_policy(policy, snapshots)
    return firewall.check(sql, connection=connection, profile=profile)


def render(verdict: Verdict) -> str:
    """Format a verdict for a person.

    Args:
        verdict: Verdict - The verdict.

    Returns:
        str - Text lines.

    """
    lines = ["allowed" if verdict.allowed else "rejected"]
    lines.extend(
        f"  {v.rule}: {v.message}" + (f"\n    hint: {v.hint}" if v.hint else "")
        for v in verdict.violations
    )
    if verdict.sql is not None:
        lines.append(f"  sql: {verdict.sql}")
    lines.extend(f"  rewrite: {rewrite}" for rewrite in verdict.rewrites)
    lines.extend(
        (
            f"  mask: output column {mask.position + 1} ({mask.column})"
            f" with {mask.strategy}"
        )
        for mask in verdict.masks
    )
    if verdict.structural_only:
        lines.append(
            "  note: structural check only; tables, columns and PII were not checked",
        )
    if verdict.policy_hash is not None:
        lines.append(f"  policy: {verdict.policy_hash}")
    return "\n".join(lines)
