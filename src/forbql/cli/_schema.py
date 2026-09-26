"""`forbql schema`: sync a connection's schema into the store, and see what changed."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from forbql.firewall import Firewall
from forbql.knowledge import erd as draw
from forbql.policy import PolicyError, UnknownProfileError, load_policy
from forbql.session import SessionError, schema_changes, sync_schema

from ._store import with_store

if TYPE_CHECKING:
    from collections.abc import Sequence

    from forbql.store import StoredSnapshot

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


@schema_app.command()
def erd(
    connection: Annotated[str, typer.Argument(help="Connection in the policy.")],
    *,
    profile: Annotated[str, typer.Option(help="Draw what this profile sees.")],
    policy: Policy,
    around: Annotated[
        list[str] | None,
        typer.Option(help="Table to centre on; repeatable."),
    ] = None,
    depth: Annotated[int, typer.Option(help="References to follow from them.")] = 1,
) -> None:
    """Print a Mermaid diagram of the synced schema, as far as the profile sees it.

    Args:
        connection: str - Connection name.
        profile: str - Profile name.
        policy: Path - Policy file.
        around: list[str] | None - Tables to centre on.
        depth: int - References to follow from them.

    Raises:
        typer.Exit: With code 2 on a wrong name, no synced schema, or too many tables.

    """
    snapshot = with_store(lambda store: store.snapshots.latest(connection))
    try:
        diagram = _diagram(
            policy,
            connection,
            profile,
            snapshot,
            around=around or (),
            depth=depth,
        )
    except (PolicyError, UnknownProfileError, ValueError, OSError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error
    typer.echo(diagram, nl=False)


def _diagram(  # ruff: ignore[too-many-arguments] - the command's options, passed on
    policy: Path,
    connection: str,
    profile: str,
    snapshot: StoredSnapshot | None,
    *,
    around: Sequence[str],
    depth: int,
) -> str:
    """Draw the synced schema as the profile sees it.

    Args:
        policy: Path - Policy file.
        connection: str - Connection name.
        profile: str - Profile name.
        snapshot: StoredSnapshot | None - The last sync.
        around: Sequence[str] - Tables to centre on.
        depth: int - References to follow from them.

    Returns:
        str - The Mermaid diagram.

    Raises:
        ValueError: If nothing was synced yet.

    """
    loaded = load_policy(policy)
    _ = loaded.profile(connection, profile)
    if snapshot is None:
        msg = f"no synced schema of {connection}: run `forbql schema sync {connection}`"
        raise ValueError(msg)
    firewall = Firewall(loaded, {connection: snapshot.catalog.snapshot()})
    visible = firewall.visible(connection, profile)
    return draw(snapshot.catalog, visible, around=around, depth=depth)
