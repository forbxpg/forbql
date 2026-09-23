from __future__ import annotations

import pytest

from forbql import Engine, Firewall, RuleId
from support.firewall import check, make_firewall, rules


def test_limit_is_added(firewall: Firewall):
    verdict = check(firewall, "SELECT id FROM accounts")

    assert verdict.sql is not None
    assert verdict.sql.endswith("LIMIT 100")
    assert verdict.rewrites == ("added LIMIT 100",)


def test_limit_above_max_rows_is_lowered(firewall: Firewall):
    verdict = check(firewall, "SELECT id FROM accounts LIMIT 5000")

    assert verdict.sql is not None
    assert verdict.sql.endswith("LIMIT 100")
    assert verdict.rewrites == ("lowered LIMIT 5000 to 100",)


def test_limit_within_max_rows_is_kept(firewall: Firewall):
    verdict = check(firewall, "SELECT id FROM accounts LIMIT 10")

    assert verdict.sql is not None
    assert verdict.sql.endswith("LIMIT 10")
    assert verdict.rewrites == ()


def test_set_operation_gets_one_outer_limit(firewall: Firewall):
    verdict = check(
        firewall,
        "SELECT id FROM accounts UNION SELECT client_id FROM accounts",
    )

    assert verdict.sql is not None
    assert verdict.sql.endswith("LIMIT 100")


def test_mysql_offset_form_keeps_the_offset():
    verdict = check(make_firewall(Engine.MYSQL), "SELECT id FROM accounts LIMIT 5, 500")

    assert verdict.sql is not None
    assert verdict.sql.endswith("LIMIT 100 OFFSET 5")


@pytest.mark.parametrize(
    ("engine", "sql"),
    [
        (Engine.POSTGRES, "SELECT id FROM accounts LIMIT (SELECT 10)"),
        (Engine.POSTGRES, "SELECT id FROM accounts FETCH FIRST 5 ROWS ONLY"),
        (Engine.SQLITE, "SELECT id FROM accounts LIMIT 1 + 1"),
    ],
)
def test_non_literal_limit_is_rejected(engine: Engine, sql: str):
    assert rules(check(make_firewall(engine), sql)) == {RuleId.INVALID_LIMIT}
