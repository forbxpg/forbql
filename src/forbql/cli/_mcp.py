"""`forbql mcp`: serve one profile of one connection to an MCP client."""

from __future__ import annotations

import getpass
from functools import partial
from pathlib import Path  # ruff: ignore[typing-only-standard-library-import]
from typing import Annotated

import typer

from forbql.policy import PolicyError, UnknownProfileError, load_policy
from forbql.session import DEFAULT_AUDIT_LOG, ForbqlSettings, Gate, connect


def mcp(  # ruff: ignore[too-many-arguments] - one parameter per command-line option
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
            help=(
                "JSON Lines file every call is recorded in instead of the store's "
                "chain; without a store, FORBQL_AUDIT_LOG sets it too."
            ),
            show_default=str(DEFAULT_AUDIT_LOG),
        ),
    ] = None,
    http: Annotated[
        bool,
        typer.Option("--http", help="Serve over HTTP with forbql tokens, not stdio."),
    ] = False,
    host: Annotated[str, typer.Option(help="Address to listen on over HTTP.")] = (
        "127.0.0.1"
    ),
    port: Annotated[int, typer.Option(help="Port to listen on over HTTP.")] = 8765,
    tls_cert: Annotated[
        Path | None,
        typer.Option(help="Certificate, to serve HTTPS yourself."),
    ] = None,
    tls_key: Annotated[Path | None, typer.Option(help="Its private key.")] = None,
    public_url: Annotated[
        str | None,
        typer.Option(help="https:// address of a proxy in front that holds TLS."),
    ] = None,
    ask_to_confirm: Annotated[
        bool,
        typer.Option(
            "--ask-to-confirm",
            help="Over HTTP, let the person at the client approve expensive queries.",
        ),
    ] = False,
) -> None:
    """Serve a profile to an MCP client: over stdio, or over HTTP with tokens.

    Over stdio nothing but MCP goes to stdout. Over HTTP every request needs a
    forbql token with a grant on this profile, and plain HTTP stays on the loopback.

    Args:
        policy: Path - Policy file.
        connection: str - Connection name.
        profile: str - Profile name.
        dsn: str | None - DSN for the connection.
        audit_log: Path | None - Audit log file.
        http: bool - Serve over HTTP.
        host: str - Address to listen on.
        port: int - Port to listen on.
        tls_cert: Path | None - Certificate for HTTPS.
        tls_key: Path | None - Its private key.
        public_url: str | None - `https://…` of a proxy in front.
        ask_to_confirm: bool - Over HTTP, ask about expensive queries rather than
            stop them; over stdio the person is always asked.

    Raises:
        typer.Exit: With code 2 when the policy is unreadable, names no such
            profile, the `mcp` extra is not installed, or HTTP would be unsafe or
            has no store for its tokens.

    """
    try:
        loaded = load_policy(policy)
        _ = loaded.profile(connection, profile)
    except (PolicyError, UnknownProfileError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error
    try:
        from forbql.mcp import (  # ruff: ignore[import-outside-top-level] - the mcp extra is optional
            ListeningError,
            build_server,
            listening,
            serve,
        )
    except ImportError as error:
        typer.echo(
            "error: the MCP server needs the extra: pip install 'forbql[mcp]'",
            err=True,
        )
        raise typer.Exit(2) from error
    try:
        where = (
            listening(
                host,
                port,
                tls_cert=tls_cert,
                tls_key=tls_key,
                public_url=public_url,
            )
            if http
            else None
        )
    except ListeningError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error
    if where is not None and ForbqlSettings().store_dsn is None:
        typer.echo("error: tokens live in the store: set FORBQL_STORE_DSN", err=True)
        raise typer.Exit(2)
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
        gate=None
        if where is None
        else Gate(loaded, connection=connection, profile=profile),
        ask=where is None or ask_to_confirm,
    )
    if where is None:
        server.run(transport="stdio", show_banner=False)
    else:
        serve(server, where)
