from __future__ import annotations

import json
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from forbql.cli import app
from support.firewall import POLICY

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def test_valid_policy_is_summarized(tmp_path: Path):
    path = tmp_path / "forbql.yaml"
    path.write_text(POLICY.format(engine="postgres", schema="public"), encoding="utf-8")

    result = runner.invoke(app, ["policy", "validate", str(path)])

    assert result.exit_code == 0
    assert "1 connection(s), 2 profile(s); sha256:" in result.stdout


def test_invalid_policy_lists_problems(tmp_path: Path):
    path = tmp_path / "forbql.yaml"
    path.write_text("version: 2\nconnections: {}\n", encoding="utf-8")

    result = runner.invoke(app, ["policy", "validate", str(path)])

    assert result.exit_code == 1
    assert "version" in result.stderr


def test_schema_is_json_schema_with_yaml_names():
    result = runner.invoke(app, ["policy", "schema"])

    schema = json.loads(result.stdout)
    assert schema["title"] == "Policy"
    assert "class" in json.dumps(schema)
