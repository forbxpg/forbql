"""`forbql mcp`: serve one profile of one connection to an MCP client over stdio."""

from __future__ import annotations

import getpass
from functools import partial
from pathlib import Path  # ruff: ignore[typing-only-standard-library-import]
from typing import Annotated

import typer

from forbql.policy import PolicyError, UnknownProfileError, load_policy
from forbql.session import DEFAULT_AUDIT_LOG, connect


def mcp(
    *,
    policy: Annotated[
        Path,
        typer.Option(help="Policy file.", envvar="FORBQL_POLICY"),
    ],
    connection: Annotated[
        str,
        typer.Option(help="Connection in the policy.", envvar="FORBQL_CONNECTION"),
    ],
    profile: Annotated[
        str,
        typer.Option(help="Profile the agent works as.", envvar="FORBQL_PROFILE"),
    ],
    dsn: Annotated[
        str | None,
        typer.Option(help="DSN; defaults to the store's or FORBQL_DSN_<CONNECTION>."),
    ] = None,
    audit_log: Annotated[
        Path | None,
        typer.Option(
            help="JSON Lines file every call is recorded in, without a store.",
            envvar="FORBQL_AUDIT_LOG",
            show_default=str(DEFAULT_AUDIT_LOG),
        ),
    ] = None,
) -> None:
    """Serve a profile to an MCP client over stdio; nothing else goes to stdout.

    Args:
        policy: Path - Policy file.
        connection: str - Connection name.
        profile: str - Profile name.
        dsn: str | None - DSN for the connection.
        audit_log: Path | None - Audit log file.

    Raises:
        typer.Exit: With code 2 when the policy is unreadable, names no such
            profile, or the `mcp` extra is not installed.

    """
    try:
        loaded = load_policy(policy)
        _ = loaded.profile(connection, profile)
    except (PolicyError, UnknownProfileError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error
    try:
        from forbql.mcp import build_server  # ruff: ignore[import-outside-top-level] - the mcp extra is optional
    except ImportError as error:
        typer.echo(
            "error: the MCP server needs the extra: pip install 'forbql[mcp]'",
            err=True,
        )
        raise typer.Exit(2) from error
    server = build_server(
        loaded,
        connection=connection,
        profile=profile,
        opener=partial(
            connect,
            loaded,
            connection=connection,
            profile=profile,
            dsn=dsn,
            audit_log=audit_log,
            principal=f"local:{getpass.getuser()}",
        ),
    )
    server.run(transport="stdio", show_banner=False)
