"""`forbql connection`: DSNs sealed in the store, never typed on the command line."""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING, Annotated

import typer

from forbql.policy import Engine  # ruff: ignore[typing-only-first-party-import] - Typer reads the annotation
from forbql.session import ForbqlSettings
from forbql.store import SecretKey, Store, StoreError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

connection_app = typer.Typer(
    help="Manage connections: their DSNs are sealed in the store.",
    no_args_is_help=True,
    add_completion=False,
)


@connection_app.command()
def add(
    name: Annotated[str, typer.Argument(help="Connection name, as in the policy.")],
    *,
    engine: Annotated[Engine, typer.Option(help="Which database it is.")],
    profile: Annotated[
        str | None,
        typer.Option(help="A profile that connects with a database role of its own."),
    ] = None,
) -> None:
    """Seal a connection's DSN in the store.

    The DSN comes from standard input or a hidden prompt: a command-line argument
    would stay in the shell's history and the process list.

    Args:
        name: str - Connection name.
        engine: Engine - Which database it is.
        profile: str | None - Profile with a DSN of its own.

    """
    if sys.stdin.isatty():
        dsn = str(typer.prompt("DSN", hide_input=True))  # pyright: ignore[reportAny]
    else:
        dsn = sys.stdin.readline().strip()
    _ = _with_store(
        lambda store: store.add_connection(name, engine, dsn, profile=profile),
    )
    whose = f" for profile {profile}" if profile else ""
    typer.echo(f"sealed the DSN of {name}{whose}")


@connection_app.command(name="list")
def list_connections() -> None:
    """List the connections in the store; DSNs stay sealed."""
    found = _with_store(lambda store: store.connections())
    for connection in found:
        own = ", ".join(connection.profiles) or "-"
        typer.echo(f"{connection.name}  {connection.engine}  own DSN: {own}")


@connection_app.command()
def remove(
    name: Annotated[str, typer.Argument(help="Connection name.")],
    *,
    profile: Annotated[
        str | None,
        typer.Option(help="Remove only this profile's own DSN."),
    ] = None,
) -> None:
    """Forget a connection, or one profile's own DSN for it.

    Args:
        name: str - Connection name.
        profile: str | None - Profile whose own DSN goes.

    Raises:
        typer.Exit: With code 1 when there was nothing to remove.

    """
    removed = _with_store(lambda store: store.remove_connection(name, profile=profile))
    what = f"the DSN of {name} for profile {profile}" if profile else name
    if not removed:
        typer.echo(f"error: no {what} in the store", err=True)
        raise typer.Exit(1)
    typer.echo(f"removed {what}")


def _with_store[T](work: Callable[[Store], Awaitable[T]]) -> T:
    """Open the store from the environment, do the work, and report failures.

    Args:
        work: Callable[[Store], Awaitable[T]] - What to do with the store.

    Returns:
        T - What the work returned.

    Raises:
        typer.Exit: With code 2 when the store is not configured, 1 when it refuses.

    """
    settings = ForbqlSettings()
    if settings.store_dsn is None:
        typer.echo(
            "error: set FORBQL_STORE_DSN: the store as its runtime role",
            err=True,
        )
        raise typer.Exit(2)
    value = settings.secret_key.get_secret_value() if settings.secret_key else None
    dsn = settings.store_dsn.get_secret_value()

    async def go() -> T:
        key = None
        if value is not None or settings.secret_key_file is not None:
            key = SecretKey.load(value, settings.secret_key_file)
        async with Store.open(dsn, key=key) as store:
            return await work(store)

    try:
        return asyncio.run(go())
    except StoreError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1) from error
