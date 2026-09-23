"""What the firewall allows is the SQL it regenerated; that SQL must run on the real engine.

Runs against the local stand: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from support.corpus import (
    DEMO,
    PROFILE,
    LegitimateCase,
    connection_name,
    demo_firewall,
    legitimate_runs,
    run_id,
)
from support.live import build_sqlite, run_as_reader

if TYPE_CHECKING:
    from pathlib import Path

    from forbql import Engine

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def sqlite_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_sqlite(
        tmp_path_factory.mktemp("demo") / "bank.db",
        DEMO / "sqlite.sql",
    )


@pytest.mark.parametrize(
    ("case", "engine"),
    legitimate_runs(),
    ids=[run_id(run) for run in legitimate_runs()],
)
def test_regenerated_sql_runs_as_the_reader(
    case: LegitimateCase,
    engine: Engine,
    sqlite_file: Path,
):
    if engine in case.known_block:
        pytest.skip("blocked by the firewall; nothing to run")
    verdict = demo_firewall().check(
        case.sql,
        connection=connection_name(engine),
        profile=PROFILE,
    )
    assert verdict.sql is not None

    outcome = run_as_reader(engine, verdict.sql, sqlite_file)

    assert outcome.error is None, verdict.sql
