from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from forbql.engines import ErrorClass, QueryError, Restriction, connect
from forbql.policy import Engine, Limits
from support.demo_db import build_demo_sqlite

if TYPE_CHECKING:
    from pathlib import Path

    from forbql.engines import QueryEngine

VISIBLE = Restriction(
    tables={
        "main.accounts": (
            "id",
            "client_id",
            "currency",
            "balance",
            "status",
            "opened_at",
        ),
        "main.clients": ("id", "full_name", "email", "phone", "region", "created_at"),
    },
    functions=frozenset(),
    allow_recursive=False,
)
LIMITS = Limits(statement_timeout_ms=500)


@pytest.fixture
def database(tmp_path: Path) -> Path:
    return build_demo_sqlite(tmp_path)


async def _open(database: Path, restriction: Restriction | None) -> QueryEngine:
    engine = await connect(Engine.SQLITE, str(database))
    _ = await engine.snapshot()
    if restriction is not None:
        await engine.restrict(restriction)
    return engine


def run(database: Path, sql: str, restriction: Restriction | None = VISIBLE):
    async def go():
        engine = await _open(database, restriction)
        try:
            return await engine.execute(sql, LIMITS)
        finally:
            await engine.close()

    return asyncio.run(go())


def failure(
    database: Path,
    sql: str,
    restriction: Restriction | None = VISIBLE,
) -> ErrorClass:
    with pytest.raises(QueryError) as caught:
        run(database, sql, restriction)
    return caught.value.error_class


def test_snapshot_lists_every_table_and_column(database: Path):
    async def go():
        engine = await connect(Engine.SQLITE, str(database))
        try:
            return await engine.snapshot()
        finally:
            await engine.close()

    snapshot = asyncio.run(go())

    assert snapshot.default_schema == "main"
    assert set(snapshot.tables) == {
        "main.accounts",
        "main.canary",
        "main.clients",
        "main.secrets",
        "main.transactions",
    }
    assert "passport" in snapshot.tables["main.clients"]


def test_visible_columns_can_be_read(database: Path):
    result = run(database, "SELECT full_name FROM clients WHERE id = 2")

    assert result.columns == ("full_name",)
    assert result.rows == (("Наина Святославовна Ершова",),)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT api_key FROM secrets",
        "SELECT passport FROM clients",
        "SELECT count(*) FROM transactions",
        "SELECT randomblob(10)",
        "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < 3) SELECT n FROM r",
        "ATTACH DATABASE ':memory:' AS x",
        "PRAGMA table_info(accounts)",
    ],
)
def test_the_authorizer_refuses_what_the_profile_does_not_list(
    database: Path,
    sql: str,
):
    assert failure(database, sql) is ErrorClass.PERMISSION_DENIED


def test_recursion_is_allowed_when_the_profile_allows_it(database: Path):
    restriction = Restriction(
        tables=VISIBLE.tables,
        functions=frozenset(),
        allow_recursive=True,
    )
    sql = "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < 3) SELECT n FROM r"

    assert run(database, sql, restriction).rows == ((1,), (2,), (3,))


def test_profile_functions_are_allowed(database: Path):
    restriction = Restriction(
        tables=VISIBLE.tables,
        functions=frozenset({"HEX"}),
        allow_recursive=False,
    )

    assert run(database, "SELECT hex(status) FROM accounts LIMIT 1", restriction).rows


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM canary",
        "UPDATE canary SET value = 'x'",
        "CREATE TABLE stolen (x INTEGER)",
    ],
)
def test_writes_fail_even_without_an_authorizer(database: Path, sql: str):
    assert failure(database, sql, restriction=None) is ErrorClass.READ_ONLY


def test_endless_query_is_interrupted(database: Path):
    sql = "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT count(*) FROM r"

    assert failure(database, sql, restriction=None) is ErrorClass.TIMEOUT


def test_second_statement_is_refused(database: Path):
    assert failure(database, "SELECT 1; SELECT 2") is ErrorClass.DATABASE


def test_missing_file_is_a_connection_error(tmp_path: Path):
    with pytest.raises(QueryError) as caught:
        asyncio.run(connect(Engine.SQLITE, str(tmp_path / "absent.db")))

    assert caught.value.error_class is ErrorClass.CONNECTION


def test_cte_reads_are_authorized_through_their_body(database: Path):
    sql = "WITH c AS (SELECT id FROM accounts) SELECT count(*) FROM c"

    assert run(database, sql).rows == ((362,),)


def test_cte_named_like_a_hidden_table_reads_only_its_body(database: Path):
    # SQLite flattens the CTE and reports the reads of its body: here, accounts.
    sql = "WITH secrets AS (SELECT id FROM accounts) SELECT count(*) FROM secrets"

    assert run(database, sql).rows == ((362,),)
