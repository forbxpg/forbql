"""What the firewall lets through reads, in the database, only what the profile sees.

The database's own planner names the tables a query reads; the firewall's view of the
query and the database's must agree on that, however the query was spoiled.

Runs against the local stand: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import tempfile
from functools import cache
from pathlib import Path

import pytest
from hypothesis import given

from forbql import Engine
from support.corpus import DEMO
from support.live import build_sqlite
from support.mutations import Target, demo_targets, spoiled
from support.touched import touched

pytestmark = pytest.mark.integration

VIEWS = {"account_totals", "client_fingerprints"}
"""The demo bank's views: the database reports the tables behind them."""


@cache
def sqlite_file() -> Path:
    # Built once per run: a function-scoped fixture would be shared by every example.
    folder = Path(tempfile.mkdtemp(prefix="forbql-fuzz-"))
    return build_sqlite(folder / "bank.db", DEMO / "sqlite.sql")


@cache
def readable(target: Target) -> frozenset[str]:
    visible = {
        name.lower()
        for name in target.firewall.visible(target.connection, target.profile)
    }
    behind = {
        table
        for name in visible
        if name.rpartition(".")[2] in VIEWS
        for table in touched(target.engine, f"SELECT * FROM {name}", sqlite_file())
        or ()
    }
    return frozenset(visible | behind)


@given(spoiled(demo_targets()))
def test_the_database_reads_only_what_the_profile_sees(
    spoiled_query: tuple[Target, str],
):
    target, sql = spoiled_query
    verdict = target.firewall.check(
        sql,
        connection=target.connection,
        profile=target.profile,
    )
    if not verdict.allowed or verdict.sql is None:
        return

    read = touched(target.engine, verdict.sql, sqlite_file())

    # A query the database refuses reads nothing: at worst a false allow, never a leak.
    assert read is None or read <= readable(target), (
        target.engine,
        sql,
        verdict.sql,
        read - readable(target),
    )


@pytest.mark.parametrize(
    ("engine", "schema"),
    [(Engine.POSTGRES, "public"), (Engine.MYSQL, "bank"), (Engine.SQLITE, "main")],
)
def test_the_planner_names_a_hidden_table_it_reads(engine: Engine, schema: str):
    # The check above means nothing if the planner never names what a query reads.
    read = touched(
        engine,
        "SELECT id FROM accounts WHERE id IN (SELECT id FROM secrets)",
        sqlite_file(),
    )

    assert read == {f"{schema}.accounts", f"{schema}.secrets"}
