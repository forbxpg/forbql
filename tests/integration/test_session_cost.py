"""The planner's estimate gates a query before it runs.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

import forbql
from forbql import Engine
from forbql.session import CostDecision
from support.corpus import DEMO
from support.stand import READER

if TYPE_CHECKING:
    from pathlib import Path

    from forbql import RunResult

pytestmark = pytest.mark.integration

LIVE = (Engine.POSTGRES, Engine.MYSQL)
CHEAP = "SELECT id FROM accounts"
# The count reads every pair: the LIMIT the firewall adds cannot make it cheap.
DEAR = "SELECT count(*) FROM accounts AS a CROSS JOIN transactions AS t"


@pytest.fixture
def policy(tmp_path: Path) -> Path:
    # Scanning one table costs more than 1 and a cross join more than 5000 on both
    # engines, whatever their statistics say.
    path = tmp_path / "forbql.yaml"
    path.write_text(
        (DEMO / "forbql.yaml")
        .read_text(encoding="utf-8")
        .replace(
            "      analyst:\n",
            "      analyst:\n        explain: { confirm_cost: 1, block_cost: 5000 }\n",
        ),
        encoding="utf-8",
    )
    return path


def run(
    engine: Engine,
    sql: str,
    policy: Path,
    audit: Path,
    *,
    confirmed: bool = False,
) -> RunResult:
    async def go() -> RunResult:
        async with forbql.connect(
            policy,
            connection=f"bank-{engine}",
            profile="analyst",
            dsn=READER[engine],
            audit_log=audit,
        ) as session:
            return await session.run(sql, confirmed=confirmed)

    return asyncio.run(go())


@pytest.mark.parametrize("engine", LIVE, ids=str)
def test_a_cheap_query_runs_with_its_estimate(engine: Engine, tmp_path: Path):
    result = run(engine, CHEAP, DEMO / "forbql.yaml", tmp_path / "audit.jsonl")

    assert result.ok
    assert result.cost is not None
    assert result.cost > 0


@pytest.mark.parametrize("engine", LIVE, ids=str)
def test_an_expensive_query_waits_for_confirmation(
    engine: Engine,
    policy: Path,
    tmp_path: Path,
):
    audit = tmp_path / "audit.jsonl"

    result = run(engine, CHEAP, policy, audit)

    assert result.decision is CostDecision.CONFIRM
    assert not result.ok
    assert result.rows == ()
    record = json.loads(audit.read_text(encoding="utf-8").splitlines()[-1])
    assert record["error_class"] == "cost_confirm"
    assert record["executed_sql"] is None


@pytest.mark.parametrize("engine", LIVE, ids=str)
def test_a_confirmed_query_runs(engine: Engine, policy: Path, tmp_path: Path):
    result = run(engine, CHEAP, policy, tmp_path / "audit.jsonl", confirmed=True)

    assert result.ok
    assert result.rows


@pytest.mark.parametrize("engine", LIVE, ids=str)
def test_a_query_past_the_block_cost_never_runs(
    engine: Engine,
    policy: Path,
    tmp_path: Path,
):
    result = run(engine, DEAR, policy, tmp_path / "audit.jsonl", confirmed=True)

    assert result.decision is CostDecision.BLOCK
    assert result.rows == ()
