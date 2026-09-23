"""Tests for the parse step."""

from __future__ import annotations

import pytest

from forbql import Engine, Firewall, RuleId, check_structure
from support.firewall import check, make_firewall, rules


@pytest.mark.parametrize(
    "sql",
    ["SELEC id FROM accounts", "SELECT id FROM", "SELECT 'unclosed"],
)
def test_unparsable_sql_is_rejected(firewall: Firewall, sql: str):
    assert rules(check(firewall, sql)) == {RuleId.PARSE_ERROR}


@pytest.mark.parametrize("sql", ["", "   ", ";"])
def test_empty_sql_is_rejected(firewall: Firewall, sql: str):
    assert rules(check(firewall, sql)) == {RuleId.PARSE_ERROR}


def test_more_than_one_statement_is_rejected(firewall: Firewall):
    verdict = check(firewall, "SELECT id FROM accounts; DELETE FROM accounts")

    assert rules(verdict) == {RuleId.MULTIPLE_STATEMENTS}


def test_trailing_semicolon_is_one_statement(firewall: Firewall):
    assert check(firewall, "SELECT id FROM accounts;").allowed


def test_overlong_sql_is_rejected(firewall: Firewall):
    sql = "SELECT id FROM accounts WHERE id IN (" + ",".join(["1"] * 60_000) + ")"

    assert rules(check(firewall, sql)) == {RuleId.PARSE_ERROR}


def test_deep_nesting_is_rejected_not_crashed(firewall: Firewall):
    sql = "SELECT " + "(" * 200 + "1" + ")" * 200

    verdict = check(firewall, sql)

    assert rules(verdict) == {RuleId.PARSE_ERROR}
    assert "nested too deeply" in verdict.violations[0].message


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id /*! , (SELECT api_key FROM secrets) */ FROM accounts",
        "SELECT id FROM accounts --/*! , (SELECT 1) */",
    ],
)
def test_mysql_executable_comment_is_rejected(sql: str):
    verdict = check(make_firewall(Engine.MYSQL), sql)

    assert rules(verdict) == {RuleId.EXECUTABLE_COMMENT}
    assert verdict.violations[0].span is not None


def test_comments_never_reach_the_database():
    verdict = check(
        make_firewall(Engine.POSTGRES),
        "SELECT id /*! x */ FROM accounts -- note",
    )

    assert verdict.allowed
    assert verdict.sql is not None
    assert "/*" not in verdict.sql
    assert "--" not in verdict.sql


@pytest.mark.parametrize(
    ("engine", "sql"),
    [
        (Engine.POSTGRES, 'SELECT "Lower"(full_name) FROM clients'),
        (Engine.SQLITE, 'SELECT "lower"(full_name) FROM clients'),
        (Engine.SQLITE, "SELECT [lower](full_name) FROM clients"),
        (Engine.MYSQL, "SELECT `lower`(full_name) FROM clients"),
    ],
)
def test_quoted_function_name_is_rejected(engine: Engine, sql: str):
    assert rules(check(make_firewall(engine), sql)) == {RuleId.QUOTED_FUNCTION_NAME}


def test_postgres_unicode_escape_identifier_is_rejected():
    sql = 'SELECT U&"\\0065mail" FROM clients'

    assert rules(check(make_firewall(Engine.POSTGRES), sql)) == {RuleId.UNICODE_ESCAPE}


@pytest.mark.parametrize(
    ("engine", "sql"),
    [(Engine.POSTGRES, "VACUUM"), (Engine.SQLITE, "EXPLAIN SELECT 1")],
)
def test_syntax_the_parser_does_not_understand_is_rejected(engine: Engine, sql: str):
    assert rules(check_structure(sql, engine)) == {RuleId.UNSUPPORTED_SYNTAX}


@pytest.mark.parametrize("engine", [Engine.POSTGRES, Engine.SQLITE])
def test_unquoted_identifiers_are_case_insensitive(engine: Engine):
    assert check(make_firewall(engine), "SELECT ID FROM ACCOUNTS").allowed
