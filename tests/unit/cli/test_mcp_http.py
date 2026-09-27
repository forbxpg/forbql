from __future__ import annotations

from typing import TYPE_CHECKING

from typer.testing import CliRunner

from forbql.cli import app
from support.corpus import DEMO

if TYPE_CHECKING:
    import pytest

runner = CliRunner()
SERVE = [
    "mcp",
    "--policy",
    str(DEMO / "forbql.yaml"),
    "--connection",
    "bank-postgres",
    "--profile",
    "analyst",
    "--http",
]


def test_plain_http_beyond_the_loopback_does_not_start():
    refused = runner.invoke(app, [*SERVE, "--host", "0.0.0.0"])  # ruff: ignore[hardcoded-bind-all-interfaces]

    assert refused.exit_code == 2
    assert "refusing plain HTTP on 0.0.0.0" in refused.stderr


def test_http_without_a_store_does_not_start(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("FORBQL_STORE_DSN", raising=False)

    refused = runner.invoke(app, SERVE)

    assert refused.exit_code == 2
    assert "tokens live in the store" in refused.stderr
