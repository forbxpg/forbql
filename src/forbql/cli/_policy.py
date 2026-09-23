"""`forbql policy`: validate a policy file and print its JSON Schema."""

from __future__ import annotations

import json
from pathlib import Path  # ruff: ignore[typing-only-standard-library-import]
from typing import Annotated

import typer

from forbql.policy import Policy, PolicyError, load_policy, policy_hash

policy_app = typer.Typer(
    help="Validate policies and print their JSON Schema.",
    no_args_is_help=True,
    add_completion=False,
)


@policy_app.command()
def validate(path: Annotated[Path, typer.Argument(help="Policy file.")]) -> None:
    """Validate a policy file; exit 1 and list the problems if it is invalid.

    Args:
        path: Path - Policy file.

    Raises:
        typer.Exit: With code 1 when the policy is invalid.

    """
    try:
        policy = load_policy(path)
    except PolicyError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    connections = len(policy.connections)
    profiles = sum(
        len(connection.profiles) for connection in policy.connections.values()
    )
    summary = f"{connections} connection(s), {profiles} profile(s)"
    typer.echo(f"{path}: valid; {summary}; {policy_hash(policy)}")


@policy_app.command()
def schema() -> None:
    """Print the JSON Schema of policy v1, for editor completion."""
    typer.echo(json.dumps(Policy.model_json_schema(by_alias=True), indent=2))
