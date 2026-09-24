"""`forbql store`: the service store's key and schema."""

from __future__ import annotations

import typer

from forbql.store import SecretKey

store_app = typer.Typer(
    help="Manage the service store.",
    no_args_is_help=True,
    add_completion=False,
)


@store_app.command()
def keygen() -> None:
    """Print a new secret key for FORBQL_SECRET_KEY."""
    typer.echo(SecretKey.generate())
