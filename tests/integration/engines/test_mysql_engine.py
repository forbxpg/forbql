"""The mysql engine on the local stand.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import pytest

from forbql.engines import ErrorClass, QueryError
from forbql.engines.mysql import MySQLEngine
from forbql.policy import Engine, Limits
from support.stand import ADMIN, READER, probe_account, seeded_names

if TYPE_CHECKING:
    from forbql.engines import ResultSet
    from forbql.firewall import SchemaSnapshot

pytestmark = pytest.mark.integration


def snapshot(dsn: str) -> SchemaSnapshot:
    async def go() -> SchemaSnapshot:
        engine = await MySQLEngine.connect(dsn)
        try:
            return await engine.snapshot()
        finally:
            await engine.close()

    return asyncio.run(go())


def execute(sql: str, limits: Limits, dsn: str = READER[Engine.MYSQL]) -> ResultSet:
    async def go() -> ResultSet:
        engine = await MySQLEngine.connect(dsn)
        try:
            _ = await engine.snapshot()
            return await engine.execute(sql, limits)
        finally:
            await engine.close()

    return asyncio.run(go())


def failure(sql: str, dsn: str = READER[Engine.MYSQL]) -> ErrorClass:
    with pytest.raises(QueryError) as caught:
        execute(sql, Limits(statement_timeout_ms=1000), dsn)
    return caught.value.error_class


def test_reader_snapshot_holds_only_what_the_role_may_read():
    found = snapshot(READER[Engine.MYSQL])
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


def test_reader_snapshot_carries_the_definitions_of_its_views():
    views = snapshot(READER[Engine.MYSQL]).views

    assert set(views) == {"bank.account_totals", "bank.client_fingerprints"}
    assert "md5(" in (views["bank.client_fingerprints"] or "")


def test_a_view_without_show_view_has_no_definition():
    with probe_account(
        Engine.MYSQL,
        ["GRANT SELECT ON bank.account_totals TO 'forbql_probe'@'%'"],
    ) as dsn:
        found = snapshot(dsn)

    assert found.views == {"bank.account_totals": None}


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
    dsn = READER[Engine.MYSQL].replace("forbql_reader@", "wrong@")

    with pytest.raises(QueryError) as caught:
        asyncio.run(MySQLEngine.connect(dsn))

    assert caught.value.error_class is ErrorClass.CONNECTION


@pytest.mark.parametrize(
    "sql",
    ["DELETE FROM canary", "UPDATE canary SET value = 'owned'"],
)
def test_the_owner_cannot_write_either(sql: str):
    admin = ADMIN[Engine.MYSQL]

    assert failure(sql, admin) is ErrorClass.READ_ONLY
    assert execute("SELECT id, value FROM canary", Limits(), admin).rows == (
        (1, "untouched"),
    )


def test_a_second_statement_is_refused_by_the_server():
    admin = ADMIN[Engine.MYSQL]

    assert failure("SELECT 1; DELETE FROM canary", admin) is ErrorClass.INVALID_QUERY
    assert execute("SELECT id, value FROM canary", Limits(), admin).rows == (
        (1, "untouched"),
    )


def test_long_query_is_cut_short():
    # MySQL interrupts SLEEP at max_execution_time and returns 1 instead of failing.
    start = time.monotonic()

    result = execute("SELECT SLEEP(10)", Limits(statement_timeout_ms=1000))

    assert result.rows == ((1,),)
    assert time.monotonic() - start < 4


@pytest.mark.parametrize("sql", ["CREATE TABLE stolen (x INT)", "DROP TABLE canary"])
def test_the_owner_cannot_change_the_schema(sql: str):
    # MySQL commits before DDL, ending a read-only transaction; the session-wide
    # read-only mode is what refuses it.
    admin = ADMIN[Engine.MYSQL]

    assert failure(sql, admin) is ErrorClass.READ_ONLY
    assert execute("SELECT id, value FROM canary", Limits(), admin).rows == (
        (1, "untouched"),
    )


def test_a_connection_lost_mid_query_stays_a_query_error():
    async def go() -> list[ErrorClass]:
        engine = await MySQLEngine.connect(READER[Engine.MYSQL])
        _ = await engine.snapshot()
        found: list[ErrorClass] = []
        for sql in ("KILL CONNECTION_ID()", "SELECT 1"):
            with pytest.raises(QueryError) as caught:
                _ = await engine.execute(sql, Limits(statement_timeout_ms=1000))
            found.append(caught.value.error_class)
        await engine.close()
        return found

    assert asyncio.run(go())[1] == ErrorClass.CONNECTION


def test_required_tls_encrypts_the_connection():
    rows = execute(
        "SHOW SESSION STATUS LIKE 'Ssl_cipher'",
        Limits(),
        READER[Engine.MYSQL] + "?ssl-mode=REQUIRED",
    ).rows

    assert rows[0][1]


def test_verifying_an_unknown_certificate_fails_to_connect():
    with pytest.raises(QueryError) as caught:
        asyncio.run(MySQLEngine.connect(READER[Engine.MYSQL] + "?ssl-mode=VERIFY_CA"))

    assert caught.value.error_class == ErrorClass.CONNECTION


def estimate(sql: str, dsn: str = READER[Engine.MYSQL]) -> float | None:
    async def go() -> float | None:
        engine = await MySQLEngine.connect(dsn)
        try:
            _ = await engine.snapshot()
            return await engine.estimate(sql, Limits(statement_timeout_ms=1000))
        finally:
            await engine.close()

    return asyncio.run(go())


def test_a_join_costs_more_than_one_of_its_tables():
    one = estimate("SELECT id FROM accounts")
    joined = estimate(
        "SELECT a.id, t.id FROM accounts AS a CROSS JOIN transactions AS t",
    )

    assert one is not None
    assert joined is not None
    assert 0 < one < joined


def test_estimating_does_not_run_the_query():
    start = time.monotonic()

    assert estimate("SELECT SLEEP(5) FROM accounts LIMIT 1") is not None
    assert time.monotonic() - start < 2


def test_estimating_a_table_the_role_may_not_read_is_refused():
    with pytest.raises(QueryError) as caught:
        estimate("SELECT api_key FROM secrets")

    assert caught.value.error_class == ErrorClass.PERMISSION_DENIED
