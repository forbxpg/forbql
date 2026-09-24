from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

import forbql
from forbql import RuleId, SessionError
from forbql.audit import verify_log
from forbql.engines import ErrorClass, QueryError
from forbql.session import ForbqlSettings, dsn_variable
from support.corpus import DEMO
from support.demo_db import build_demo_sqlite

if TYPE_CHECKING:
    from pathlib import Path

    from forbql import RunResult

POLICY = DEMO / "forbql.yaml"
CONNECTION = "bank-sqlite"


@pytest.fixture
def database(tmp_path: Path) -> Path:
    return build_demo_sqlite(tmp_path)


def run(sql: str, database: Path, audit: Path, **options: object) -> RunResult:
    async def go() -> RunResult:
        async with forbql.connect(
            POLICY,
            connection=CONNECTION,
            profile="analyst",
            dsn=str(database),
            audit_log=audit,
            **options,  # pyright: ignore[reportArgumentType]
        ) as session:
            return await session.run(sql)

    return asyncio.run(go())


def audit_lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_allowed_query_returns_masked_rows(database: Path, tmp_path: Path):
    result = run(
        "SELECT id, email FROM clients WHERE id = 1",
        database,
        tmp_path / "a.jsonl",
    )

    assert result.ok
    assert result.columns == ("id", "email")
    assert result.rows[0][0] == 1
    assert str(result.rows[0][1]).startswith("***")


def test_rejected_query_is_audited_and_never_runs(database: Path, tmp_path: Path):
    audit = tmp_path / "a.jsonl"

    result = run("SELECT api_key FROM secrets", database, audit)

    assert not result.ok
    assert {v.rule for v in result.verdict.violations} == {RuleId.TABLE_NOT_ALLOWED}
    (entry,) = audit_lines(audit)
    assert entry["allowed"] is False
    assert entry["executed_sql"] is None
    assert entry["rules"] == ["table_not_allowed"]


def test_every_run_leaves_a_chained_record(database: Path, tmp_path: Path):
    audit = tmp_path / "a.jsonl"

    run("SELECT count(*) FROM accounts", database, audit)
    run("SELECT id FROM accounts LIMIT 2", database, audit, principal="agent-7")

    first, second = audit_lines(audit)
    assert second["previous"] == first["hash"]
    assert second["principal"] == "agent-7"
    assert second["rows"] == 2
    assert verify_log(audit).intact


def test_database_failure_is_classified_and_audited_in_full(
    database: Path,
    tmp_path: Path,
):
    audit = tmp_path / "a.jsonl"
    sql = "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT count(*) FROM r"
    policy = tmp_path / "forbql.yaml"
    policy.write_text(
        POLICY.read_text(encoding="utf-8").replace(
            "  bank-sqlite:\n    engine: sqlite\n    profiles:\n      analyst:\n",
            (
                "  bank-sqlite:\n    engine: sqlite\n    profiles:\n      analyst:\n"
                "        allow_recursive_cte: true\n        limits: { statement_timeout_ms: 300 }\n"
            ),
        ),
        encoding="utf-8",
    )

    async def go() -> RunResult:
        async with forbql.connect(
            policy,
            connection=CONNECTION,
            profile="analyst",
            dsn=str(database),
            audit_log=audit,
        ) as session:
            return await session.run(sql)

    result = asyncio.run(go())

    assert result.error is ErrorClass.TIMEOUT
    assert result.hint is not None
    (entry,) = audit_lines(audit)
    assert entry["error_class"] == "timeout"
    assert entry["error_detail"] == "interrupted"


def test_dsn_comes_from_the_environment(
    database: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv(dsn_variable(CONNECTION), str(database))

    async def go() -> RunResult:
        async with forbql.connect(
            POLICY,
            connection=CONNECTION,
            profile="analyst",
            audit_log=tmp_path / "a.jsonl",
        ) as session:
            return await session.run("SELECT count(*) FROM accounts")

    assert asyncio.run(go()).ok


def test_missing_dsn_names_the_variable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv(dsn_variable(CONNECTION), raising=False)

    async def go() -> None:
        async with forbql.connect(
            POLICY,
            connection=CONNECTION,
            profile="analyst",
            audit_log=tmp_path / "a",
        ):
            pass

    with pytest.raises(SessionError, match="FORBQL_DSN_BANK_SQLITE"):
        asyncio.run(go())


def test_hash_strategy_needs_a_key(
    database: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    policy = tmp_path / "forbql.yaml"
    policy.write_text(
        POLICY.read_text(encoding="utf-8").replace(
            "strategy: partial",
            "strategy: hash",
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("FORBQL_MASK_KEY", raising=False)

    async def go(sql: str) -> RunResult:
        async with forbql.connect(
            policy,
            connection=CONNECTION,
            profile="analyst",
            dsn=str(database),
            audit_log=tmp_path / "a.jsonl",
        ) as session:
            return await session.run(sql)

    with pytest.raises(SessionError, match="FORBQL_MASK_KEY"):
        asyncio.run(go("SELECT email FROM clients"))

    monkeypatch.setenv("FORBQL_MASK_KEY", "k" * 32)
    result = asyncio.run(go("SELECT email FROM clients WHERE id = 1"))

    assert len(str(result.rows[0][0])) == 16


def test_the_authorizer_stands_behind_the_firewall(database: Path, tmp_path: Path):
    async def go() -> None:
        async with forbql.connect(
            POLICY,
            connection=CONNECTION,
            profile="analyst",
            dsn=str(database),
            audit_log=tmp_path / "a.jsonl",
        ) as session:
            engine = session._engine  # the firewall is bypassed on purpose
            await engine.execute("SELECT api_key FROM secrets", session._target.limits)

    with pytest.raises(QueryError):
        asyncio.run(go())


def test_unreachable_database_is_a_session_error(tmp_path: Path):
    async def go() -> None:
        async with forbql.connect(
            POLICY,
            connection=CONNECTION,
            profile="analyst",
            dsn=str(tmp_path / "absent.db"),
            audit_log=tmp_path / "a.jsonl",
        ):
            pass

    with pytest.raises(SessionError, match="cannot open connection 'bank-sqlite'"):
        asyncio.run(go())


def test_a_dsn_never_shows_in_the_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        dsn_variable("bank-postgres"),
        "postgresql://reader:hunter2@db/bank",
    )

    settings = ForbqlSettings()

    assert "hunter2" not in repr(settings)
    assert settings.dsn["bank_postgres"].get_secret_value().endswith("@db/bank")


def test_the_audit_log_path_comes_from_the_environment(
    database: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    target = tmp_path / "from-env.jsonl"
    monkeypatch.setenv("FORBQL_AUDIT_LOG", str(target))

    async def go() -> RunResult:
        async with forbql.connect(
            POLICY,
            connection=CONNECTION,
            profile="analyst",
            dsn=str(database),
        ) as session:
            return await session.run("SELECT count(*) FROM accounts")

    assert asyncio.run(go()).ok
    assert len(audit_lines(target)) == 1
