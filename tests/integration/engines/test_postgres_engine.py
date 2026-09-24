"""The postgres engine on the local stand.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
from time import monotonic
from typing import TYPE_CHECKING

import pytest

from forbql import Engine
from forbql.engines import ErrorClass, QueryError, ResultSet
from forbql.engines.postgres import PostgresEngine
from forbql.policy import Limits
from support.stand import ADMIN, READER, seeded_names

if TYPE_CHECKING:
    from forbql import SchemaSnapshot

pytestmark = pytest.mark.integration


def snapshot(dsn: str = READER[Engine.POSTGRES]) -> SchemaSnapshot:
    """The schema snapshot of the local stand.

    Args:
        dsn: str - The DSN of the local stand.

    Returns:
        SchemaSnapshot - The schema snapshot.

    """

    async def _go() -> SchemaSnapshot:
        engine = await PostgresEngine.connect(dsn)
        try:
            return await engine.snapshot()
        finally:
            await engine.close()

    return asyncio.run(_go())


def execute(sql: str, limits: Limits, dsn: str = READER[Engine.POSTGRES]) -> ResultSet:

    async def _go() -> ResultSet:
        engine = await PostgresEngine.connect(dsn)
        try:
            _ = await engine.snapshot()
            return await engine.execute(sql, limits)
        finally:
            await engine.close()

    return asyncio.run(_go())


def failure(sql: str, dsn: str = READER[Engine.POSTGRES]) -> ErrorClass:
    """The error class of a failed query.

    Args:
        sql: str - The SQL query to execute.
        dsn: str - The DSN of the local stand.

    Returns:
        ErrorClass - The error class.

    """
    with pytest.raises(QueryError) as caught:
        execute(sql, Limits(statement_timeout_ms=1000), dsn)
    return caught.value.error_class


def test_reader_snapshot_holds_only_what_the_role_may_read():
    found = snapshot(READER[Engine.POSTGRES])
    schema = found.default_schema

    assert set(found.tables) == {
        f"{schema}.{name}"
        for name in (
            "account_totals",
            "accounts",
            "client_fingerprints",
            "clients",
            "transactions",
        )
    }
    assert "passport" not in found.tables[f"{schema}.clients"]
    assert "email" in found.tables[f"{schema}.clients"]


def test_non_ascii_text_comes_back_as_seeded():
    result = execute(
        "SELECT id, full_name FROM clients ORDER BY id",
        Limits(max_rows=1000),
    )

    assert result.rows == seeded_names()


def test_rows_stop_at_the_cap():
    result = execute("SELECT id FROM transactions", Limits(max_rows=10))

    assert len(result.rows) == 10
    assert result.truncated is True


def test_errors_are_classified():
    assert failure("SELECT no_such_column FROM accounts") is ErrorClass.INVALID_QUERY
    assert failure("SELECT api_key FROM secrets") is ErrorClass.PERMISSION_DENIED


def test_wrong_password_is_a_connection_error():
    dsn = READER[Engine.POSTGRES].replace("forbql_reader@", "wrong@")

    with pytest.raises(QueryError) as caught:
        asyncio.run(PostgresEngine.connect(dsn))

    assert caught.value.error_class is ErrorClass.CONNECTION


@pytest.mark.parametrize(
    "sql",
    ["DELETE FROM canary", "UPDATE canary SET value = 'owned'"],
)
def test_the_owner_cannot_write_either(sql: str):
    admin = ADMIN[Engine.POSTGRES]

    assert failure(sql, admin) is ErrorClass.READ_ONLY
    assert execute("SELECT id, value FROM canary", Limits(), admin).rows == (
        (1, "untouched"),
    )


def test_a_second_statement_is_refused_by_the_server():
    admin = ADMIN[Engine.POSTGRES]

    assert failure("SELECT 1; DELETE FROM canary", admin) is ErrorClass.INVALID_QUERY
    assert execute("SELECT id, value FROM canary", Limits(), admin).rows == (
        (1, "untouched"),
    )


def test_long_query_stops_at_the_time_limit():
    start = monotonic()

    assert failure("SELECT pg_sleep(10)") is ErrorClass.TIMEOUT
    assert monotonic() - start < 4


def test_a_connection_lost_mid_query_stays_a_connection_error():
    async def go() -> list[QueryError]:
        engine = await PostgresEngine.connect(READER[Engine.POSTGRES])
        _ = await engine.snapshot()
        found: list[QueryError] = []
        for sql in ("SELECT pg_terminate_backend(pg_backend_pid())", "SELECT 1"):
            with pytest.raises(QueryError) as caught:
                _ = await engine.execute(sql, Limits(statement_timeout_ms=1000))
            found.append(caught.value)
        await engine.close()
        return found

    lost, after = asyncio.run(go())

    assert [lost.error_class, after.error_class] == [ErrorClass.CONNECTION] * 2
    # The failed rollback must not replace the error that lost the connection.
    assert "in the middle of operation" in lost.detail
