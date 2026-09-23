from __future__ import annotations

import pytest

from forbql import Engine, Firewall, RuleId
from support.firewall import check, make_firewall, rules


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO accounts (id) VALUES (1)",
        "UPDATE accounts SET balance = 0",
        "DELETE FROM accounts",
        "DROP TABLE accounts",
        "CREATE TABLE x (id INT)",
        "ALTER TABLE accounts ADD COLUMN x INT",
        "(SELECT id FROM accounts)",
    ],
)
def test_only_queries_are_allowed(firewall: Firewall, sql: str):
    assert rules(check(firewall, sql)) == {RuleId.NOT_A_QUERY}


@pytest.mark.parametrize(
    ("engine", "sql"),
    [
        (Engine.POSTGRES, "SET ROLE postgres"),
        (Engine.POSTGRES, "TRUNCATE accounts"),
        (Engine.MYSQL, "SHOW TABLES"),
        (Engine.SQLITE, "PRAGMA table_info(accounts)"),
        (Engine.SQLITE, "ATTACH DATABASE 'x.db' AS x"),
    ],
)
def test_engine_specific_statements_are_not_queries(engine: Engine, sql: str):
    verdict = check(make_firewall(engine), sql)

    assert not verdict.allowed
    assert rules(verdict) & {RuleId.NOT_A_QUERY, RuleId.UNSUPPORTED_SYNTAX}


def test_data_modifying_cte_is_rejected():
    sql = "WITH gone AS (DELETE FROM accounts RETURNING id) SELECT id FROM gone"

    assert RuleId.WRITE_OPERATION in rules(check(make_firewall(Engine.POSTGRES), sql))


@pytest.mark.parametrize(
    ("engine", "sql"),
    [
        (Engine.POSTGRES, "SELECT id INTO copy FROM accounts"),
        (Engine.MYSQL, "SELECT id INTO @x FROM accounts"),
    ],
)
def test_select_into_is_rejected(engine: Engine, sql: str):
    assert RuleId.SELECT_INTO in rules(check(make_firewall(engine), sql))


def test_mysql_into_outfile_does_not_parse():
    sql = "SELECT id FROM accounts INTO OUTFILE '/tmp/x'"

    assert rules(check(make_firewall(Engine.MYSQL), sql)) == {RuleId.PARSE_ERROR}


@pytest.mark.parametrize("engine", [Engine.POSTGRES, Engine.MYSQL])
@pytest.mark.parametrize("lock", ["FOR UPDATE", "FOR SHARE"])
def test_row_locks_are_rejected(engine: Engine, lock: str):
    verdict = check(make_firewall(engine), f"SELECT id FROM accounts {lock}")

    assert rules(verdict) == {RuleId.ROW_LOCK}


@pytest.mark.parametrize(
    ("engine", "sql"),
    [
        (Engine.POSTGRES, "SELECT id FROM accounts WHERE id = $1"),
        (Engine.SQLITE, "SELECT id FROM accounts WHERE id = ?"),
        (Engine.MYSQL, "SELECT @@version"),
        (Engine.MYSQL, "SELECT @x := 1"),
        (Engine.MYSQL, "SELECT id FROM accounts WHERE id = @x"),
    ],
)
def test_parameters_and_variables_are_rejected(engine: Engine, sql: str):
    assert rules(check(make_firewall(engine), sql)) == {RuleId.VARIABLE}


@pytest.mark.parametrize("operation", ["UNION", "UNION ALL", "INTERSECT", "EXCEPT"])
def test_set_operations_are_queries(firewall: Firewall, operation: str):
    verdict = check(
        firewall,
        f"SELECT id FROM accounts {operation} SELECT client_id FROM accounts",
    )

    assert verdict.allowed
