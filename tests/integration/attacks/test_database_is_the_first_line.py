"""With the firewall off, the engine and the database must stop what they can.

Runs against the local stand: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from forbql import Engine
from support.corpus import DEMO, AttackCase, Effect, attack_runs, run_id
from support.live import (
    TIMEOUT_SECONDS,
    as_admin,
    build_sqlite,
    run_as_admin,
    run_as_reader,
)

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
    request: pytest.FixtureRequest,
):
    if engine in case.pending:
        # A marker, not pytest.xfail(): the test still runs, and a pass fails CI.
        request.applymarker(pytest.mark.xfail(reason=case.pending[engine], strict=True))

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


WRITES = [run for run in LIVE if Effect.CANARY_UNCHANGED in run[0].effects]


@pytest.mark.parametrize(
    ("case", "engine"),
    WRITES,
    ids=[run_id(run) for run in WRITES],
)
def test_read_only_transaction_stops_writes_even_for_the_owner(
    case: AttackCase,
    engine: Engine,
    sqlite_file: Path,
):
    # The owner may write anything; only the engine's read-only transaction is left.
    outcome = run_as_admin(engine, case.sql, sqlite_file)

    assert outcome.error is not None
    assert as_admin(engine, "SELECT id, value FROM canary", sqlite_file) == [
        (1, "untouched"),
    ]
