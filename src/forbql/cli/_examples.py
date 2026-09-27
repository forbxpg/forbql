"""`forbql examples`: review the examples agents propose."""

from __future__ import annotations

import asyncio
import getpass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from forbql.policy import PolicyError, UnknownProfileError
from forbql.session import (
    SessionError,
    approve_example,
    proposals,
    reject_example,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from forbql.store import StoredProposal

examples_app = typer.Typer(
    help="Review the examples agents propose: list, approve, reject.",
    no_args_is_help=True,
    add_completion=False,
)

Policy = Annotated[Path, typer.Option(help="Policy file.", envvar="FORBQL_POLICY")]
Number = Annotated[int, typer.Argument(help="The proposal's number, from `list`.")]


@examples_app.command(name="list")
def list_command(
    *,
    connection: Annotated[
        str | None,
        typer.Option(help="Only this connection's proposals."),
    ] = None,
    approved: Annotated[
        bool,
        typer.Option("--approved", help="Approved examples instead of waiting ones."),
    ] = False,
) -> None:
    """Show proposals in full: read every word before approving one.

    Characters that do not print are shown escaped, so nothing in a question hides
    from the reader.

    Args:
        connection: str | None - Only this connection's.
        approved: bool - Approved ones instead of those waiting.

    """
    found = _run(proposals(connection=connection, approved=approved))
    if not found:
        typer.echo("nothing approved" if approved else "nothing waits for review")
    for proposal in found:
        typer.echo(_shown(proposal))


@examples_app.command()
def approve(number: Number, *, policy: Policy) -> None:
    """Check a proposal under its proposer's profile again, then let search show it.

    Args:
        number: int - The proposal's number.
        policy: Path - Policy file.

    """
    done = _run(approve_example(policy, number, by=_operator()))
    typer.echo(f"approved {number}: {_visible(done.proposal.question, lines=False)}")
    typer.echo(f"  seen by: {', '.join(done.reach.seen)}")
    for profile, why in done.reach.hidden.items():
        typer.echo(f"  hidden from {profile}: {why}")


@examples_app.command()
def reject(number: Number, *, policy: Policy) -> None:
    """Drop a proposal; an approved one leaves search.

    Args:
        number: int - The proposal's number.
        policy: Path - Policy file; the audit record names it.

    """
    dropped = _run(reject_example(policy, number, by=_operator()))
    was = "; search no longer shows it" if dropped.approved_at is not None else ""
    typer.echo(f"rejected {number}: {_visible(dropped.question, lines=False)}{was}")


def _run[T](work: Coroutine[object, object, T]) -> T:
    """Run a command's work, turning refusals into an error and exit code 2.

    Args:
        work: Coroutine[object, object, T] - The work.

    Returns:
        T - What it returned.

    Raises:
        typer.Exit: With code 2 when the store, the policy or the proposal refuses.

    """
    try:
        return asyncio.run(work)
    except (PolicyError, UnknownProfileError, SessionError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error


def _operator() -> str:
    """Name the operator as the audit records it.

    Returns:
        str - `local:<user>`.

    """
    return f"local:{getpass.getuser()}"


def _shown(proposal: StoredProposal) -> str:
    """Write a proposal out for review.

    Args:
        proposal: StoredProposal - The proposal.

    Returns:
        str - Its header line, question and query.

    """
    when = proposal.proposed_at.strftime("%Y-%m-%d %H:%M")
    head = f"{proposal.id}  {proposal.connection}  {proposal.profile}  "
    head += f"{proposal.author}  {when}"
    if proposal.approved_by is not None:
        head += f"  approved by {proposal.approved_by}"
    question = _visible(proposal.question, lines=False)
    sql = _visible(proposal.sql).replace("\n", "\n       ")
    return f"{head}\n  question: {question}\n  sql: {sql}"


def _visible(text: str, *, lines: bool = True) -> str:
    """Escape the characters that do not print.

    Args:
        text: str - Text an agent wrote.
        lines: bool - Keep line breaks; without it they are escaped too.

    Returns:
        str - The text, every hidden character shown as its escape.

    """
    return "".join(
        c
        if c.isprintable() or (lines and c == "\n")
        else c.encode("unicode_escape").decode()
        for c in text
    )
