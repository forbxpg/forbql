"""`forbql store`: the service store's key and schema."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import typer
from sqlalchemy.exc import SQLAlchemyError

from forbql.session import ForbqlSettings, secret_key
from forbql.store import SecretKey, Store, StoreError
from forbql.store import migrate as migrate_store

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

store_app = typer.Typer(
    help="Manage the service store.",
    no_args_is_help=True,
    add_completion=False,
)


@store_app.command()
def keygen() -> None:
    """Print a new secret key for FORBQL_SECRET_KEY."""
    typer.echo(SecretKey.generate())


@store_app.command()
def migrate() -> None:
    """Bring the store's schema up to this forbql, as the role that owns it.

    The store's DSN for that role comes from FORBQL_STORE_OWNER_DSN.

    Raises:
        typer.Exit: 2 when the variable is missing, 1 when the store refuses.

    """
    settings = ForbqlSettings()
    if settings.store_owner_dsn is None:
        typer.echo(
            "error: set FORBQL_STORE_OWNER_DSN: the store as its owner",
            err=True,
        )
        raise typer.Exit(2)
    try:
        revision = migrate_store(settings.store_owner_dsn.get_secret_value())
    except (SQLAlchemyError, OSError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo(f"the store is at revision {revision}")


def with_store[T](work: Callable[[Store], Awaitable[T]]) -> T:
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
    dsn = settings.store_dsn.get_secret_value()

    async def go() -> T:
        async with Store.open(dsn, key=secret_key(settings)) as store:
            return await work(store)

    try:
        return asyncio.run(go())
    except StoreError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1) from error
