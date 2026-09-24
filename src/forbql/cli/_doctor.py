"""`forbql doctor`: which guarantees hold right now, and which do not."""

from __future__ import annotations

import asyncio
from pathlib import Path  # ruff: ignore[typing-only-standard-library-import]
from typing import TYPE_CHECKING, Annotated

import typer

from forbql.audit import verify_log
from forbql.policy import PolicyError, UnknownProfileError, load_policy
from forbql.session import DEFAULT_AUDIT_LOG, SessionError, diagnose

if TYPE_CHECKING:
    from forbql.policy import Policy


def doctor(
    *,
    policy: Annotated[
        Path,
        typer.Option(help="Policy file.", envvar="FORBQL_POLICY"),
    ],
    connection: Annotated[
        list[str] | None,
        typer.Option(help="Connection to check; every one in the policy by default."),
    ] = None,
    audit_log: Annotated[
        Path | None,
        typer.Option(
            help="JSON Lines audit log to verify.",
            envvar="FORBQL_AUDIT_LOG",
            show_default=str(DEFAULT_AUDIT_LOG),
        ),
    ] = None,
) -> None:
    """Run the startup checks on every profile and verify the audit log.

    DSNs come from the `FORBQL_DSN_<CONNECTION>` variables.

    Args:
        policy: Path - Policy file.
        connection: list[str] | None - Connections to check.
        audit_log: Path | None - Audit log file.

    Raises:
        typer.Exit: Always; 0 when every guarantee holds, 1 when one does not, 2 when
            the policy cannot be read.

    """
    try:
        loaded = load_policy(policy)
        names = connection or list(loaded.connections)
        profiles = [
            (name, p) for name in names for p in loaded.connection(name).profiles
        ]
    except (PolicyError, UnknownProfileError, OSError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error
    healthy = [_check_profile(loaded, name, profile) for name, profile in profiles]
    healthy.append(_check_audit(audit_log or DEFAULT_AUDIT_LOG))
    raise typer.Exit(0 if all(healthy) else 1)


def _check_profile(policy: Policy, connection: str, profile: str) -> bool:
    """Print what the startup checks find for one profile.

    Args:
        policy: Policy - The policy.
        connection: str - Connection name.
        profile: str - Profile name.

    Returns:
        bool - Whether a session would open.

    """
    typer.echo(f"{connection} / {profile}")
    try:
        found = asyncio.run(diagnose(policy, connection=connection, profile=profile))
    except SessionError as error:
        typer.echo(f"  error    {error}")
        return False
    for line in found.refusals:
        typer.echo(f"  refused  {line}")
    for line in found.warnings:
        typer.echo(f"  warning  {line}")
    if found.ok:
        typer.echo("  ok       the role only reads; listed views pass the allowlist")
    return found.ok


def _check_audit(path: Path) -> bool:
    """Print whether the audit log's chain holds.

    Args:
        path: Path - Audit log file.

    Returns:
        bool - Whether the chain holds; a log not written yet holds.

    """
    typer.echo(f"audit log {path}")
    if not path.is_file():
        typer.echo("  ok       no records yet")
        return True
    result = verify_log(path)
    if result.intact:
        typer.echo(f"  ok       intact; {result.records} record(s)")
    else:
        typer.echo(f"  broken   line {result.broken_at}: {result.reason}")
    return result.intact
