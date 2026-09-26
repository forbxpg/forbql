"""`forbql schema`: sync a connection's schema into the store, and see what changed."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from forbql.policy import PolicyError, UnknownProfileError
from forbql.session import SessionError, schema_changes, sync_schema

schema_app = typer.Typer(
    help="Sync schemas into the store and compare them.",
    no_args_is_help=True,
    add_completion=False,
)

Policy = Annotated[Path, typer.Option(help="Policy file.", envvar="FORBQL_POLICY")]


@schema_app.command()
def sync(
    connection: Annotated[str, typer.Argument(help="Connection in the policy.")],
    *,
    policy: Policy,
) -> None:
    """Read the connection's schema and keep it as the reviewed one.

    Until the next sync, sessions see only what this version has.

    Args:
        connection: str - Connection name.
        policy: Path - Policy file.

    Raises:
        typer.Exit: With code 2 when the store, the policy or the database refuses.

    """
    try:
        done = asyncio.run(sync_schema(policy, connection=connection))
    except (PolicyError, UnknownProfileError, SessionError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error
    if not done.changes:
        typer.echo(f"{connection}: no changes; still version {done.version}")
        return
    typer.echo(f"{connection}: version {done.version}")
    for change in done.changes:
        typer.echo(f"  {change}")


@schema_app.command()
def diff(
    connection: Annotated[str, typer.Argument(help="Connection in the policy.")],
    *,
    policy: Policy,
) -> None:
    """Show what changed in the connection's schema since the last sync.

    Args:
        connection: str - Connection name.
        policy: Path - Policy file.

    Raises:
        typer.Exit: With code 1 when something changed, 2 on a refusal.

    """
    try:
        changes = asyncio.run(schema_changes(policy, connection=connection))
    except (PolicyError, UnknownProfileError, SessionError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error
    if not changes:
        typer.echo(f"{connection}: no changes since the last sync")
        return
    for change in changes:
        typer.echo(change)
    raise typer.Exit(1)
