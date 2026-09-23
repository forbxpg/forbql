from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from forbql import Engine
from forbql.cli import app
from support.firewall import POLICY, snapshot

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


@pytest.fixture
def policy_file(tmp_path: Path) -> Path:
    path = tmp_path / "forbql.yaml"
    path.write_text(POLICY.format(engine="postgres", schema="public"), encoding="utf-8")
    return path


@pytest.fixture
def schema_file(tmp_path: Path) -> Path:
    path = tmp_path / "bank.json"
    path.write_text(snapshot(Engine.POSTGRES).model_dump_json(), encoding="utf-8")
    return path


def test_structural_check_needs_only_a_dialect():
    result = runner.invoke(app, ["check", "SELECT 1", "--dialect", "sqlite"])

    assert result.exit_code == 0
    assert result.stdout.startswith("allowed")
    assert "structural check only" in result.stdout


def test_rejection_exits_with_one_and_names_the_rule():
    result = runner.invoke(app, ["check", "DELETE FROM accounts", "--dialect", "mysql"])

    assert result.exit_code == 1
    assert "not_a_query" in result.stdout


def test_full_check_with_policy_and_schema(policy_file: Path, schema_file: Path):
    args = [
        "--policy",
        str(policy_file),
        "--connection",
        "bank",
        "--profile",
        "analyst",
    ]

    allowed = runner.invoke(
        app,
        ["check", "SELECT email FROM clients", *args, "--schema", str(schema_file)],
    )
    hidden = runner.invoke(
        app,
        ["check", "SELECT api_key FROM secrets", *args, "--schema", str(schema_file)],
    )

    assert allowed.exit_code == 0
    assert "mask: output column 1 (public.clients.email) with partial" in allowed.stdout
    assert "structural" not in allowed.stdout
    assert hidden.exit_code == 1
    assert "table_not_allowed" in hidden.stdout


def test_json_output_is_the_verdict(policy_file: Path):
    args = [
        "--policy",
        str(policy_file),
        "--connection",
        "bank",
        "--profile",
        "analyst",
    ]

    result = runner.invoke(app, ["check", "SELECT id FROM accounts", *args, "--json"])

    verdict = json.loads(result.stdout)
    assert verdict["allowed"] is True
    assert verdict["structural_only"] is True
    assert verdict["policy_hash"].startswith("sha256:")


def test_sql_can_come_from_stdin():
    result = runner.invoke(
        app,
        ["check", "-", "--dialect", "postgres"],
        input="SELECT 1",
    )

    assert result.exit_code == 0


@pytest.mark.parametrize(
    "args",
    [
        ["check", "SELECT 1"],
        ["check", "SELECT 1", "--dialect", "postgres", "--profile", "analyst"],
        ["check", "SELECT 1", "--policy", "forbql.yaml"],
    ],
)
def test_incomplete_options_are_a_usage_error(args: list[str]):
    assert runner.invoke(app, args).exit_code == 2


def test_dialect_conflicts_with_policy(policy_file: Path):
    args = ["check", "SELECT 1", "--policy", str(policy_file), "--dialect", "mysql"]

    assert (
        runner.invoke(
            app,
            [*args, "--connection", "bank", "--profile", "analyst"],
        ).exit_code
        == 2
    )


def test_unknown_profile_is_an_error(policy_file: Path):
    args = ["--policy", str(policy_file), "--connection", "bank", "--profile", "admin"]

    result = runner.invoke(app, ["check", "SELECT 1", *args])

    assert result.exit_code == 2
    assert "profile 'admin'" in result.stderr
