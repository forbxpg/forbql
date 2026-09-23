"""With the firewall off, the database itself must stop what it can.

Runs against the local stand: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from forbql import Engine
from support.corpus import DEMO, AttackCase, Effect, attack_runs, run_id
from support.live import TIMEOUT_SECONDS, as_admin, build_sqlite, run_as_reader

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

LIVE = [run for run in attack_runs() if run[0].effects]


@pytest.fixture(scope="session")
def sqlite_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_sqlite(
        tmp_path_factory.mktemp("demo") / "bank.db",
        DEMO / "sqlite.sql",
    )


@pytest.fixture(scope="session")
def sentinels(sqlite_file: Path) -> dict[Engine, set[str]]:
    """Values no attack may return: API keys and passports.

    Returns:
        dict[Engine, set[str]] - The values per engine.

    """
    sql = "SELECT api_key FROM secrets UNION ALL SELECT passport FROM clients"
    return {
        engine: {str(row[0]) for row in as_admin(engine, sql, sqlite_file)}
        for engine in Engine
    }


@pytest.mark.parametrize(("case", "engine"), LIVE, ids=[run_id(run) for run in LIVE])
def test_database_stops_the_attack(
    case: AttackCase,
    engine: Engine,
    sqlite_file: Path,
    sentinels: dict[Engine, set[str]],
):
    if engine in case.pending:
        pytest.xfail(case.pending[engine])

    outcome = run_as_reader(engine, case.sql, sqlite_file)

    if Effect.DENIED in case.effects:
        assert outcome.error is not None, (
            f"the database ran it and returned {outcome.rows[:3]}"
        )
    if Effect.CANARY_UNCHANGED in case.effects:
        assert as_admin(engine, "SELECT id, value FROM canary", sqlite_file) == [
            (1, "untouched"),
        ]
    if Effect.NO_SECRETS in case.effects:
        assert not sentinels[engine] & set(outcome.cells())
    if Effect.BOUNDED in case.effects:
        assert outcome.seconds < TIMEOUT_SECONDS + 3
