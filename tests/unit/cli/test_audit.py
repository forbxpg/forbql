"""`forbql audit show`: the latest records, never a broken chain presented as history."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from forbql.audit import GENESIS, Action, AuditRecord
from forbql.cli import app

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

runner = CliRunner()
WHEN = datetime(2026, 9, 27, 15, 4, tzinfo=UTC)


def entry(previous: str, **fields: object) -> AuditRecord:
    base: dict[str, object] = {
        "at": WHEN,
        "principal": "local",
        "connection": "bank",
        "profile": "analyst",
        "action": Action.SQL_RUN,
        "policy_hash": "sha256:x",
        "executed_sql": "SELECT 1",
        "allowed": True,
        "rules": (),
        "rows": 1,
        "size": 1,
        "truncated": False,
        "duration_ms": 3,
        "error_class": None,
        "error_detail": None,
        "previous": previous,
        "hash": "",
    }
    draft = AuditRecord.model_validate({**base, **fields})
    return draft.model_copy(update={"hash": draft.expected_hash()})


def write(path: Path, records: list[AuditRecord]) -> None:
    lines = [record.model_dump_json() for record in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def chain(path: Path) -> list[AuditRecord]:
    first = entry(GENESIS, sql="SELECT 1")
    second = entry(
        first.hash,
        sql="SELECT secret\x1b",
        executed_sql=None,
        allowed=False,
        rules=("table_not_allowed",),
        rows=0,
        size=0,
        duration_ms=4,
    )
    third = entry(
        second.hash,
        sql="SELECT 1\nFROM accounts",
        duration_ms=5,
        truncated=True,
        error_class="query_failed",
    )
    records = [first, second, third]
    write(path, records)
    return records


def test_show_prints_the_latest_records(tmp_path: Path):
    path = tmp_path / "audit.jsonl"
    chain(path)

    result = runner.invoke(app, ["audit", "show", str(path), "--limit", "1"])

    assert result.exit_code == 0
    assert result.stdout == (
        "2026-09-27 15:04Z  local  bank  analyst  sql.run  allowed  5ms  "
        "query_failed  truncated\n"
        "  SELECT 1\n"
        "  FROM accounts\n"
    )


def test_filters_keep_the_latest_matching_records(tmp_path: Path):
    path = tmp_path / "audit.jsonl"
    chain(path)

    denied = runner.invoke(app, ["audit", "show", str(path), "--denied"])
    latest = runner.invoke(
        app,
        ["audit", "show", str(path), "--action", "sql.run", "--limit", "2"],
    )

    assert denied.exit_code == 0
    assert denied.stdout == (
        "2026-09-27 15:04Z  local  bank  analyst  sql.run  "
        "denied (table_not_allowed)  4ms\n"
        "  SELECT secret\\x1b\n"
    )
    assert latest.exit_code == 0
    assert "3ms" not in latest.stdout
    assert "4ms" in latest.stdout
    assert "5ms" in latest.stdout


def test_a_search_can_be_selected_on_its_own(tmp_path: Path):
    path = tmp_path / "audit.jsonl"
    first = entry(GENESIS, sql="SELECT 1")
    second = entry(
        first.hash,
        action=Action.SCHEMA_SEARCH,
        sql="сколько денег",
        executed_sql=None,
        rows=2,
        duration_ms=8,
    )
    write(path, [first, second])

    result = runner.invoke(
        app,
        ["audit", "show", str(path), "--action", "schema.search"],
    )

    assert result.exit_code == 0
    assert result.stdout == (
        "2026-09-27 15:04Z  local  bank  analyst  schema.search  allowed  8ms\n"
        "  сколько денег\n"
    )


def test_a_broken_chain_shows_only_what_holds(tmp_path: Path):
    path = tmp_path / "audit.jsonl"
    records = chain(path)
    content = path.read_text(encoding="utf-8").splitlines()
    altered = json.loads(content[1])
    altered["sql"] = "SELECT stolen"
    content[1] = json.dumps(altered)
    path.write_text("\n".join(content) + "\n", encoding="utf-8")

    result = runner.invoke(app, ["audit", "show", str(path)])

    assert result.exit_code == 1
    assert "SELECT stolen" not in result.stdout
    assert "SELECT 1\n" in result.stdout
    assert f"{path}: broken at line 2: record altered" in result.stdout
    assert "1 record(s) before it hold" in result.stdout
    assert records[0].sql == "SELECT 1"


def test_an_empty_log_says_so(tmp_path: Path):
    path = tmp_path / "audit.jsonl"
    path.write_bytes(b"")

    result = runner.invoke(app, ["audit", "show", str(path)])

    assert result.exit_code == 0
    assert result.stdout == "no audit records\n"


def test_a_missing_file_is_an_error(tmp_path: Path):
    result = runner.invoke(app, ["audit", "show", str(tmp_path / "absent.jsonl")])

    assert result.exit_code == 2
    assert "no audit log" in result.stderr


def test_the_store_is_required_when_no_file_is_given(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("FORBQL_STORE_DSN", raising=False)

    result = runner.invoke(app, ["audit", "show"])

    assert result.exit_code == 2
    assert "FORBQL_STORE_DSN" in result.stderr
