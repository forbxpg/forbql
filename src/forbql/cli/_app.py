"""The `forbql` application and its commands."""

from __future__ import annotations

import typer

from ._check import check
from ._policy import policy_app

app = typer.Typer(
    name="forbql",
    help="The SQL firewall for AI agents.",
    no_args_is_help=True,
    add_completion=False,
)
_ = app.command()(check)
app.add_typer(policy_app, name="policy")
