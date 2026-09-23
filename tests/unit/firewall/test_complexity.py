from __future__ import annotations

from forbql import Firewall, RuleId
from support.firewall import check, rules

THREE_JOINS = (
    "SELECT a.id FROM accounts a "
    "JOIN transactions t ON t.account_id = a.id "
    "JOIN clients c ON c.id = a.client_id "
    "JOIN accounts b ON b.client_id = c.id"
)
RECURSIVE = "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n WHERE x < 5) SELECT x FROM n"


def test_joins_up_to_the_limit_are_allowed(firewall: Firewall):
    sql = "SELECT a.id FROM accounts a JOIN transactions t ON t.account_id = a.id, clients c"

    assert check(firewall, sql).allowed


def test_joins_over_the_limit_are_rejected(firewall: Firewall):
    assert rules(check(firewall, THREE_JOINS)) == {RuleId.TOO_MANY_JOINS}


def test_nesting_up_to_the_limit_is_allowed(firewall: Firewall):
    sql = "SELECT id FROM accounts WHERE id IN (SELECT id FROM accounts WHERE id IN (SELECT 1))"

    assert check(firewall, sql).allowed


def test_nesting_over_the_limit_is_rejected(firewall: Firewall):
    sql = (
        "SELECT id FROM accounts WHERE id IN (SELECT id FROM accounts WHERE id IN "
        "(SELECT id FROM accounts WHERE id IN (SELECT 1)))"
    )

    assert rules(check(firewall, sql)) == {RuleId.SUBQUERY_TOO_DEEP}


def test_recursive_cte_needs_the_profile_to_allow_it(firewall: Firewall):
    assert rules(check(firewall, RECURSIVE)) == {RuleId.RECURSIVE_CTE}
    assert check(firewall, RECURSIVE, profile="auditor").allowed
