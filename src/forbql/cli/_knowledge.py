"""`forbql knowledge`: search the synced schema, and rebuild its index."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from forbql.knowledge import LIMIT
from forbql.policy import PolicyError, UnknownProfileError
from forbql.session import SessionError, connect, reindex

if TYPE_CHECKING:
    from forbql.knowledge import SearchHit

knowledge_app = typer.Typer(
    help="Search what forbql knows about a schema.",
    no_args_is_help=True,
    add_completion=False,
)

Policy = Annotated[Path, typer.Option(help="Policy file.", envvar="FORBQL_POLICY")]


@knowledge_app.command()
def search(
    question: Annotated[
        str,
        typer.Argument(help="What you want to know, any language."),
    ],
    *,
    connection: Annotated[str, typer.Option(help="Connection in the policy.")],
    profile: Annotated[str, typer.Option(help="Search what this profile sees.")],
    policy: Policy,
    limit: Annotated[int, typer.Option(help="Tables to show.")] = LIMIT,
) -> None:
    """Find the tables a question needs, among those the profile sees.

    Args:
        question: str - The question.
        connection: str - Connection name.
        profile: str - Profile name.
        policy: Path - Policy file.
        limit: int - Tables to show.

    Raises:
        typer.Exit: With code 2 when the session cannot open or has no store.

    """

    async def go() -> list[SearchHit]:
        async with connect(policy, connection=connection, profile=profile) as session:
            return await session.search(question, limit=limit)

    try:
        hits = asyncio.run(go())
    except (PolicyError, UnknownProfileError, SessionError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error
    for hit in hits:
        joined = f"  joins {hit.joined_from}" if hit.joined_from else ""
        typer.echo(f"{hit.table} ({', '.join(hit.columns)}){joined}")


@knowledge_app.command(name="reindex")
def reindex_command(
    connection: Annotated[str, typer.Argument(help="Connection in the policy.")],
    *,
    policy: Policy,
) -> None:
    """Embed the synced schema again, as after a change of model.

    Args:
        connection: str - Connection name.
        policy: Path - Policy file.

    Raises:
        typer.Exit: With code 2 when there is no store or no synced schema.

    """
    try:
        done = asyncio.run(reindex(policy, connection=connection))
    except (PolicyError, UnknownProfileError, SessionError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error
    typer.echo(f"{connection}: {done.embedded} embedded, {done.removed} removed")
