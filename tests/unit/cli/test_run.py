from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from forbql.cli import app
from support.corpus import DEMO
from support.demo_db import build_demo_sqlite

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


@pytest.fixture
def options(tmp_path: Path) -> list[str]:
    database = build_demo_sqlite(tmp_path)
    return [
        "--policy",
        str(DEMO / "forbql.yaml"),
        "--connection",
        "bank-sqlite",
        "--profile",
        "analyst",
        "--dsn",
        str(database),
        "--audit-log",
        str(tmp_path / "audit.jsonl"),
    ]


def test_rows_come_back_as_a_table(options: list[str]):
    result = runner.invoke(
        app,
        ["run", "SELECT id, email FROM clients WHERE id = 1", *options],
    )

    assert result.exit_code == 0
    header, rule, row, footer = result.stdout.splitlines()
    assert header.split() == ["id", "email"]
    assert set(rule.replace(" ", "")) == {"-"}
    assert row.split()[1].startswith("***")
    assert footer == "(1 rows)"


def test_rejection_exits_with_one(options: list[str]):
    result = runner.invoke(app, ["run", "SELECT api_key FROM secrets", *options])

    assert result.exit_code == 1
    assert "table_not_allowed" in result.stdout


def test_json_output_carries_the_verdict(options: list[str]):
    result = runner.invoke(
        app,
        ["run", "SELECT count(*) AS n FROM accounts", *options, "--json"],
    )

    body = json.loads(result.stdout)
    assert body["columns"] == ["n"]
    assert body["rows"] == [[362]]
    assert body["verdict"]["allowed"] is True


def test_missing_dsn_is_a_usage_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("FORBQL_DSN_BANK_SQLITE", raising=False)
    args = [
        "run",
        "SELECT 1",
        "--policy",
        str(DEMO / "forbql.yaml"),
        "--connection",
        "bank-sqlite",
    ]

    result = runner.invoke(
        app,
        [*args, "--profile", "analyst", "--audit-log", str(tmp_path / "a")],
    )

    assert result.exit_code == 2
    assert "FORBQL_DSN_BANK_SQLITE" in result.stderr


def test_audit_verify_reports_an_intact_log(options: list[str], tmp_path: Path):
    runner.invoke(app, ["run", "SELECT count(*) FROM accounts", *options])

    result = runner.invoke(app, ["audit", "verify", str(tmp_path / "audit.jsonl")])

    assert result.exit_code == 0
    assert "intact; 1 record(s)" in result.stdout


def test_audit_verify_finds_tampering(options: list[str], tmp_path: Path):
    runner.invoke(app, ["run", "SELECT count(*) FROM accounts", *options])
    log = tmp_path / "audit.jsonl"
    log.write_text(
        log.read_text(encoding="utf-8").replace('"rows":1', '"rows":0'),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["audit", "verify", str(log)])

    assert result.exit_code == 1
    assert "broken at line 1" in result.stdout


def test_audit_verify_needs_a_file(tmp_path: Path):
    assert (
        runner.invoke(
            app,
            ["audit", "verify", str(tmp_path / "absent.jsonl")],
        ).exit_code
        == 2
    )


def test_startup_warnings_go_to_standard_error(options: list[str]):
    result = runner.invoke(app, ["run", "SELECT count(*) FROM accounts", *options])

    assert result.exit_code == 0
    assert result.stderr.startswith("warning: the process may write")
    assert "warning" not in result.stdout


def test_json_output_carries_the_estimate(options: list[str]):
    result = runner.invoke(
        app,
        ["run", "SELECT count(*) AS n FROM accounts", *options, "--json", "--confirm"],
    )

    assert result.exit_code == 0
    document = json.loads(result.stdout)
    assert document["decision"] == "ok"
    assert document["cost"] is None
