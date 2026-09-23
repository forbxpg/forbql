from __future__ import annotations

import pytest

from forbql import Engine, Firewall, RuleId
from forbql.firewall import ColumnMask
from forbql.policy import MaskStrategy
from support.firewall import SCHEMA, check, rules


def test_masked_column_in_outer_select_is_masked(engine: Engine, firewall: Firewall):
    verdict = check(firewall, "SELECT id, email AS contact FROM clients")

    assert verdict.allowed
    assert verdict.masks == (
        ColumnMask(
            position=1,
            column=f"{SCHEMA[engine]}.clients.email",
            strategy=MaskStrategy.PARTIAL,
            keep_last=4,
        ),
    )


def test_star_masks_the_expanded_column(engine: Engine, firewall: Firewall):
    verdict = check(firewall, "SELECT * FROM clients", profile="auditor")

    assert verdict.allowed
    assert verdict.masks == (
        ColumnMask(
            position=1,
            column=f"{SCHEMA[engine]}.clients.email",
            strategy=MaskStrategy.REDACT,
            keep_last=4,
        ),
    )


def test_star_over_an_aggregate_only_column_is_rejected_with_a_hint(firewall: Firewall):
    verdict = check(firewall, "SELECT * FROM clients")

    assert rules(verdict) == {RuleId.PII_AGGREGATE_ONLY}
    assert "instead of SELECT *" in (verdict.violations[0].hint or "")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM clients WHERE email = 'a@b.c'",
        "SELECT id FROM clients WHERE email LIKE 'a%'",
        "SELECT id FROM clients ORDER BY email",
        "SELECT email AS e FROM clients ORDER BY e",
        "SELECT email FROM clients ORDER BY 1",
        "SELECT email, count(*) FROM clients GROUP BY email",
        "SELECT lower(email) FROM clients",
        "SELECT count(DISTINCT email) FROM clients",
        "SELECT a.id FROM accounts a JOIN clients c ON c.email = a.status",
        "SELECT id FROM clients WHERE id IN (SELECT id FROM clients WHERE email = 'x')",
        "SELECT e FROM (SELECT email AS e FROM clients) s",
        "WITH c AS (SELECT email FROM clients) SELECT email FROM c",
        "SELECT email FROM clients UNION SELECT status FROM accounts",
        "SELECT * FROM (SELECT * FROM clients) s",
    ],
)
def test_masked_column_outside_the_outer_select_is_rejected(
    firewall: Firewall,
    sql: str,
):
    assert RuleId.PII_MASKED in rules(check(firewall, sql))


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT count(phone) FROM clients",
        "SELECT region, count(DISTINCT phone) AS phones FROM clients GROUP BY region",
        "SELECT region FROM clients GROUP BY region HAVING count(DISTINCT phone) > 1",
    ],
)
def test_aggregate_only_column_may_be_counted(firewall: Firewall, sql: str):
    verdict = check(firewall, sql)

    assert verdict.allowed
    assert verdict.masks == ()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT phone FROM clients",
        "SELECT id FROM clients WHERE phone = '1'",
        "SELECT max(phone) FROM clients",
        "SELECT count(lower(phone)) FROM clients",
        "SELECT region FROM clients GROUP BY region ORDER BY min(phone)",
    ],
)
def test_aggregate_only_column_elsewhere_is_rejected(firewall: Firewall, sql: str):
    assert rules(check(firewall, sql)) == {RuleId.PII_AGGREGATE_ONLY}


def test_deny_column_does_not_exist(firewall: Firewall):
    assert rules(check(firewall, "SELECT passport FROM clients")) == {
        RuleId.UNKNOWN_COLUMN,
    }
