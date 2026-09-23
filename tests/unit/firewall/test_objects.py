from __future__ import annotations

import pytest

from forbql import Engine, Firewall, RuleId
from support.firewall import HIDDEN, SCHEMA, check, make_firewall, rules


def test_visible_tables_are_allowed(firewall: Firewall):
    assert check(
        firewall,
        "SELECT a.id FROM accounts a JOIN transactions t ON t.account_id = a.id",
    ).allowed


def test_hidden_and_missing_tables_look_the_same(engine: Engine, firewall: Firewall):
    hidden = check(firewall, "SELECT id FROM secrets")
    missing = check(firewall, "SELECT id FROM no_such_table")
    schema = SCHEMA[engine]

    assert rules(hidden) == rules(missing) == {RuleId.TABLE_NOT_ALLOWED}
    assert hidden.violations[0].message == f"table {schema}.secrets is not available"
    assert (
        missing.violations[0].message
        == f"table {schema}.no_such_table is not available"
    )


def test_table_hint_names_only_visible_tables(firewall: Firewall):
    hint = check(firewall, "SELECT id FROM acounts").violations[0].hint

    assert hint is not None
    assert "accounts" in hint
    assert all(name not in hint for name in HIDDEN)


def test_other_schema_is_not_allowed(firewall: Firewall):
    assert rules(check(firewall, "SELECT id FROM other.accounts")) == {
        RuleId.TABLE_NOT_ALLOWED,
    }


@pytest.mark.parametrize(
    ("engine", "sql"),
    [
        (Engine.POSTGRES, "SELECT relname FROM pg_catalog.pg_class"),
        (Engine.POSTGRES, "SELECT usename FROM pg_user"),
        (Engine.POSTGRES, "SELECT table_name FROM information_schema.tables"),
        (Engine.MYSQL, "SELECT user FROM mysql.user"),
        (Engine.MYSQL, "SELECT table_name FROM information_schema.tables"),
        (Engine.MYSQL, "SELECT * FROM performance_schema.threads"),
        (Engine.SQLITE, "SELECT sql FROM sqlite_master"),
        (Engine.SQLITE, "SELECT sql FROM sqlite_schema"),
        (Engine.SQLITE, "SELECT sql FROM temp.sqlite_temp_master"),
    ],
)
def test_system_catalogs_are_rejected(engine: Engine, sql: str):
    assert rules(check(make_firewall(engine), sql)) == {RuleId.SYSTEM_CATALOG}


@pytest.mark.parametrize(
    ("engine", "sql"),
    [
        (Engine.POSTGRES, "SELECT g FROM generate_series(1, 3) AS g"),
        (Engine.SQLITE, "SELECT name FROM pragma_table_info('accounts')"),
        (Engine.SQLITE, "SELECT value FROM json_each('[1]')"),
    ],
)
def test_table_functions_are_rejected(engine: Engine, sql: str):
    assert RuleId.TABLE_FUNCTION in rules(check(make_firewall(engine), sql))


def test_cte_may_shadow_a_hidden_table_name(firewall: Firewall):
    sql = "WITH secrets AS (SELECT id FROM accounts) SELECT id FROM secrets"
    assert check(firewall, sql).allowed
