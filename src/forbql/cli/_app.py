"""The `forbql` application and its commands."""

from __future__ import annotations

import typer

from ._audit import audit_app
from ._check import check
from ._connection import connection_app
from ._doctor import doctor
from ._policy import policy_app
from ._run import run
from ._store import store_app

app = typer.Typer(
    name="forbql",
    help="The SQL firewall for AI agents.",
    no_args_is_help=True,
    add_completion=False,
)
_ = app.command()(check)
_ = app.command()(run)
_ = app.command()(doctor)
app.add_typer(policy_app, name="policy")
app.add_typer(audit_app, name="audit")
app.add_typer(store_app, name="store")
app.add_typer(connection_app, name="connection")
