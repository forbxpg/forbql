from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from forbql.cli import app
from support.corpus import DEMO
from support.demo_db import build_demo_sqlite

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()
POLICY = DEMO / "forbql.yaml"


@pytest.fixture
def database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = build_demo_sqlite(tmp_path)
    monkeypatch.setenv("FORBQL_DSN_BANK_SQLITE", str(path))
    return path


def doctor(tmp_path: Path, *options: str, policy: Path = POLICY):
    return runner.invoke(
        app,
        [
            "doctor",
            "--policy",
            str(policy),
            "--connection",
            "bank-sqlite",
            "--audit-log",
            str(tmp_path / "audit.jsonl"),
            *options,
        ],
    )


def test_a_read_only_file_holds_every_guarantee(database: Path, tmp_path: Path):
    database.chmod(0o444)

    result = doctor(tmp_path)

    assert result.exit_code == 0
    assert result.stdout.splitlines() == [
        "bank-sqlite / analyst",
        "  ok       the role only reads; listed views pass the allowlist",
        f"audit log {tmp_path / 'audit.jsonl'}",
        "  ok       no records yet",
    ]


@pytest.mark.usefixtures("database")
def test_a_warning_does_not_fail_the_check(tmp_path: Path):
    result = doctor(tmp_path)

    assert result.exit_code == 0
    assert "  warning  the process may write" in result.stdout


def test_a_view_outside_the_allowlist_fails_the_check(
    database: Path,
    tmp_path: Path,
):
    listed = '          main.account_totals: { columns: "*" }\n'
    policy = tmp_path / "forbql.yaml"
    policy.write_text(
        POLICY.read_text(encoding="utf-8").replace(
            listed,
            listed + '          main.client_fingerprints: { columns: "*" }\n',
        ),
        encoding="utf-8",
    )
    database.chmod(0o444)

    result = doctor(tmp_path, policy=policy)

    assert result.exit_code == 1
    assert (
        "  refused  view main.client_fingerprints: function hex is not allowed"
        in result.stdout.splitlines()
    )


def test_a_connection_without_a_dsn_fails_the_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("FORBQL_DSN_BANK_SQLITE", raising=False)

    result = doctor(tmp_path)

    assert result.exit_code == 1
    assert result.stdout.splitlines()[1].startswith("  error    ")
    assert "FORBQL_DSN_BANK_SQLITE" in result.stdout


@pytest.mark.usefixtures("database")
def test_a_broken_audit_log_fails_the_check(tmp_path: Path):
    (tmp_path / "audit.jsonl").write_text("not a record\n", encoding="utf-8")

    result = doctor(tmp_path)

    assert result.exit_code == 1
    assert "  broken   line 1: not an audit record" in result.stdout


def test_an_unknown_connection_is_a_usage_error():
    result = runner.invoke(
        app,
        ["doctor", "--policy", str(POLICY), "--connection", "nowhere"],
    )

    assert result.exit_code == 2
    assert "nowhere" in result.stderr
