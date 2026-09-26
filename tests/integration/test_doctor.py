"""`forbql doctor` against the local stand: every connection of the demo policy.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from forbql import Engine
from forbql.cli import app
from support.corpus import DEMO
from support.demo_db import build_demo_sqlite
from support.stand import ADMIN, READER

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

runner = CliRunner()


def doctor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dsns: dict[Engine, str]):
    database = build_demo_sqlite(tmp_path)
    database.chmod(0o444)
    monkeypatch.setenv("FORBQL_DSN_BANK_SQLITE", str(database))
    for engine, dsn in dsns.items():
        monkeypatch.setenv(f"FORBQL_DSN_BANK_{engine.upper()}", dsn)
    return runner.invoke(
        app,
        [
            "doctor",
            "--policy",
            str(DEMO / "forbql.yaml"),
            "--audit-log",
            str(tmp_path / "audit.jsonl"),
        ],
    )


def test_the_demo_readers_hold_every_guarantee(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    result = doctor(tmp_path, monkeypatch, READER)

    assert result.exit_code == 0, result.stdout
    assert result.stdout.count("  ok       the role only reads") == len(Engine)


def test_the_owners_are_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    result = doctor(tmp_path, monkeypatch, ADMIN)

    assert result.exit_code == 1
    assert "  refused  the role has SUPERUSER" in result.stdout.splitlines()
    assert "  refused  the account holds global privileges" in result.stdout
