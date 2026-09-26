"""`forbql token`: tokens for HTTP clients, issued and revoked on this host only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path  # ruff: ignore[typing-only-standard-library-import]
from typing import Annotated

import typer

from forbql.access import DEFAULT_LIFETIME, Grant, issue_token
from forbql.policy import PolicyError, UnknownProfileError, load_policy

from ._store import with_store

token_app = typer.Typer(
    help="Manage tokens for HTTP clients.",
    no_args_is_help=True,
    add_completion=False,
)


@token_app.command()
def create(
    name: Annotated[str, typer.Argument(help="What to call it; unique.")],
    *,
    grant: Annotated[
        list[str],
        typer.Option(help="connection:profile:capability[,capability]; repeatable."),
    ],
    policy: Annotated[
        Path,
        typer.Option(help="Policy the grants must name.", envvar="FORBQL_POLICY"),
    ],
    days: Annotated[
        int,
        typer.Option(help="Days until it expires; at most 365."),
    ] = DEFAULT_LIFETIME.days,
) -> None:
    """Issue a token; it is printed once and kept nowhere.

    The token goes to standard output alone, so it can be piped into a secret store;
    what it is goes to standard error.

    Args:
        name: str - What to call it.
        grant: list[str] - Its grants.
        policy: Path - Policy file.
        days: int - Days until it expires.

    Raises:
        typer.Exit: With code 2 when a grant or the policy is wrong.

    """
    try:
        loaded = load_policy(policy)
        grants = [Grant.parse(text) for text in grant]
        for each in grants:
            _ = loaded.profile(each.connection, each.profile)
    except (PolicyError, UnknownProfileError, ValueError, OSError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error
    lifetime = timedelta(days=days)
    try:
        issued = with_store(
            lambda store: issue_token(store, name, grants, lifetime=lifetime),
        )
    except ValueError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error
    typer.echo(issued.value)
    expires = f"{issued.expires_at:%Y-%m-%d}"
    note = f"token {issued.token_id} ({name}), expires {expires}; shown once"
    typer.echo(note, err=True)


@token_app.command(name="list")
def list_tokens() -> None:
    """List tokens with their state and grants; never their secrets."""
    now = datetime.now(UTC)
    for token in with_store(lambda store: store.tokens.all()):
        if token.revoked_at is not None:
            state = "revoked"
        elif token.expires_at <= now:
            state = "expired"
        else:
            state = f"until {token.expires_at:%Y-%m-%d}"
        grants = " ".join(
            f"{grant.connection}:{grant.profile}:{','.join(grant.capabilities)}"
            for grant in token.grants
        )
        typer.echo(f"{token.token_id}  {token.name}  {state}  {grants}")


@token_app.command()
def revoke(token_id: Annotated[str, typer.Argument(help="The token's id.")]) -> None:
    """Revoke a token; it stops working at its next request.

    Args:
        token_id: str - The token's id, as `forbql token list` shows it.

    Raises:
        typer.Exit: With code 1 when there is no live token with that id.

    """
    if not with_store(lambda store: store.tokens.revoke(token_id)):
        typer.echo(f"error: no live token {token_id}", err=True)
        raise typer.Exit(1)
    typer.echo(f"revoked {token_id}")
