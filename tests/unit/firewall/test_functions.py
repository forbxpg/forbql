from __future__ import annotations

import pytest

from forbql import Engine, Firewall, RuleId
from support.firewall import check, make_firewall, rules


@pytest.mark.parametrize(
    ("engine", "sql"),
    [
        (Engine.POSTGRES, "SELECT set_config('role', 'postgres', false)"),
        (Engine.POSTGRES, "SELECT current_setting('is_superuser')"),
        (Engine.POSTGRES, "SELECT pg_sleep(10)"),
        (Engine.POSTGRES, "SELECT pg_read_file('/etc/passwd')"),
        (Engine.POSTGRES, "SELECT pg_advisory_lock(1)"),
        (Engine.POSTGRES, "SELECT pg_notify('c', 'x')"),
        (Engine.POSTGRES, "SELECT dblink('host=evil', 'SELECT 1')"),
        (Engine.POSTGRES, "SELECT lo_import('/etc/passwd')"),
        (
            Engine.POSTGRES,
            "SELECT query_to_xml('SELECT * FROM secrets', true, true, '')",
        ),
        (Engine.MYSQL, "SELECT sleep(10)"),
        (Engine.MYSQL, "SELECT benchmark(1000000, md5('x'))"),
        (Engine.MYSQL, "SELECT load_file('/etc/passwd')"),
        (Engine.MYSQL, "SELECT get_lock('x', 10)"),
        (Engine.SQLITE, "SELECT load_extension('evil')"),
        (Engine.SQLITE, "SELECT readfile('/etc/passwd')"),
        (Engine.SQLITE, "SELECT randomblob(1000000000)"),
    ],
)
def test_dangerous_functions_are_not_allowlisted(engine: Engine, sql: str):
    assert rules(check(make_firewall(engine), sql)) == {RuleId.FUNCTION_NOT_ALLOWED}


def test_function_is_matched_by_its_own_name_not_its_argument():
    # Func.name would return "id" here, the name of the first argument.
    verdict = check(make_firewall(Engine.POSTGRES), "SELECT pg_sleep(id) FROM accounts")

    assert rules(verdict) == {RuleId.FUNCTION_NOT_ALLOWED}
    assert verdict.violations[0].message == "function pg_sleep is not allowed"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT pg_catalog.lower(status) FROM accounts",
        "SELECT evil.lower(status) FROM accounts",
    ],
)
def test_schema_qualified_calls_are_rejected(sql: str):
    assert rules(check(make_firewall(Engine.POSTGRES), sql)) == {
        RuleId.QUALIFIED_FUNCTION,
    }


@pytest.mark.parametrize(
    ("engine", "sql"),
    [
        (Engine.POSTGRES, "SELECT id::regclass FROM accounts"),
        (Engine.POSTGRES, "SELECT CAST(id AS evil_type) FROM accounts"),
        (Engine.POSTGRES, "SELECT status::json FROM accounts"),
        (Engine.SQLITE, "SELECT CAST(status AS BLOB) FROM accounts"),
    ],
)
def test_casts_to_non_builtin_types_are_rejected(engine: Engine, sql: str):
    assert rules(check(make_firewall(engine), sql)) == {RuleId.CAST_NOT_ALLOWED}


def test_operator_syntax_is_rejected():
    sql = "SELECT id OPERATOR(pg_catalog.+) 1 FROM accounts"

    assert rules(check(make_firewall(Engine.POSTGRES), sql)) == {RuleId.OPERATOR_SYNTAX}


def test_profile_may_allow_more_functions(engine: Engine):
    firewall = make_firewall(engine)

    assert rules(check(firewall, "SELECT md5(status) FROM accounts")) == {
        RuleId.FUNCTION_NOT_ALLOWED,
    }
    assert check(
        firewall,
        "SELECT md5(status) FROM accounts",
        profile="auditor",
    ).allowed


def test_function_hint_suggests_allowed_names(firewall: Firewall):
    hint = check(firewall, "SELECT lowr(status) FROM accounts").violations[0].hint

    assert hint is not None
    assert hint.startswith("nearest allowed functions: lower")
