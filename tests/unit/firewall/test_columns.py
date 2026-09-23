from __future__ import annotations

import pytest

from forbql import Engine, Firewall, RuleId
from support.firewall import HIDDEN, check, make_firewall, rules


def test_unknown_column_gets_a_nearest_visible_hint(firewall: Firewall):
    verdict = check(firewall, "SELECT balanse FROM accounts")

    assert rules(verdict) == {RuleId.UNKNOWN_COLUMN}
    assert verdict.violations[0].message == "column balanse is not available"
    assert verdict.violations[0].hint == "nearest allowed columns: balance"


@pytest.mark.parametrize(
    ("hidden", "table"),
    [("internal_score", "clients"), ("passport", "clients"), ("currency", "accounts")],
)
def test_hidden_deny_and_missing_columns_look_the_same(
    firewall: Firewall,
    hidden: str,
    table: str,
):
    verdict = check(firewall, f"SELECT {hidden} FROM {table}")
    missing = check(firewall, f"SELECT no_such_column FROM {table}")

    assert rules(verdict) == rules(missing) == {RuleId.UNKNOWN_COLUMN}
    assert verdict.violations[0].message == f"column {hidden} is not available"
    assert all(name not in (verdict.violations[0].hint or "") for name in HIDDEN)


def test_qualified_unknown_column_is_rejected(firewall: Firewall):
    verdict = check(firewall, "SELECT a.currency FROM accounts a")

    assert rules(verdict) == {RuleId.UNKNOWN_COLUMN}
    assert verdict.violations[0].message == "column a.currency is not available"


def test_star_expands_to_visible_columns_only(firewall: Firewall):
    verdict = check(firewall, "SELECT * FROM accounts")

    assert verdict.allowed
    assert verdict.sql is not None
    assert "balance" in verdict.sql
    assert "currency" not in verdict.sql


def test_unknown_column_of_a_derived_table_is_rejected(firewall: Firewall):
    sql = "SELECT d.balance FROM (SELECT id FROM accounts) d"

    assert rules(check(firewall, sql)) == {RuleId.UNKNOWN_COLUMN}


def test_correlated_subquery_resolves_outer_columns(firewall: Firewall):
    sql = (
        "SELECT a.id FROM accounts a WHERE EXISTS "
        "(SELECT 1 FROM transactions t WHERE t.account_id = a.id)"
    )

    assert check(firewall, sql).allowed


def test_order_by_output_alias_is_allowed(firewall: Firewall):
    assert check(firewall, "SELECT balance AS b FROM accounts ORDER BY b").allowed


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT to_jsonb(c) FROM clients c",
        "SELECT row_to_json(c) FROM clients c",
        "SELECT c FROM clients c",
        "SELECT (c).email FROM clients c",
    ],
)
def test_whole_row_references_are_rejected(sql: str):
    verdict = check(make_firewall(Engine.POSTGRES), sql)

    assert RuleId.WHOLE_ROW_REFERENCE in rules(verdict)


def test_ambiguous_column_names_its_visible_owners(firewall: Firewall):
    verdict = check(firewall, "SELECT id FROM accounts a, transactions t")

    assert rules(verdict) == {RuleId.AMBIGUOUS_COLUMN}
    assert verdict.violations[0].hint == "qualify it: a.id, t.id"


def test_unknown_table_alias_is_an_unknown_column(firewall: Firewall):
    verdict = check(firewall, "SELECT x.id FROM accounts a")

    assert rules(verdict) == {RuleId.UNKNOWN_COLUMN}
    assert verdict.violations[0].message == "column x.id is not available"


def test_column_the_qualifier_cannot_place_is_rejected(firewall: Firewall):
    verdict = check(firewall, "SELECT id FROM accounts JOIN transactions USING (nope)")

    assert rules(verdict) == {RuleId.UNKNOWN_COLUMN}


def test_composite_field_access_is_rejected():
    verdict = check(
        make_firewall(Engine.POSTGRES),
        "SELECT (a.status).x FROM accounts a",
    )

    assert rules(verdict) == {RuleId.FIELD_ACCESS}
