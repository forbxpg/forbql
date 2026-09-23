"""Switch each rule off in turn: some attack must then get through.

A rule no attack depends on is either dead or untested; both hide mistakes.
"""

from __future__ import annotations

import pytest

from forbql import RuleId
from support.corpus import PROFILE, attack_runs, connection_name, demo_firewall
from support.disable import disable_rule

# Without these there is no query tree to continue with, so switching them off only
# moves the failure elsewhere.
GATES = {
    RuleId.PARSE_ERROR,
    RuleId.MULTIPLE_STATEMENTS,
    RuleId.UNSUPPORTED_SYNTAX,
    RuleId.NOT_A_QUERY,
    RuleId.INTERNAL_ERROR,
}
# Another rule stops the same attacks; these stay for a precise message, and
# unicode_escape also guards structural checks, where no snapshot exposes the misread
# identifier as an unknown column.
SHADOWED = {
    RuleId.SYSTEM_CATALOG: "table_not_allowed: catalogs are in no profile",
    RuleId.TABLE_FUNCTION: "function_not_allowed: table functions are not allowlisted",
    RuleId.UNICODE_ESCAPE: 'unknown_column: U&"..." is misread as a column named u',
}
NOT_ATTACKED = {RuleId.AMBIGUOUS_COLUMN}
LOAD_BEARING = sorted(set(RuleId) - GATES - set(SHADOWED) - NOT_ATTACKED)


def _through(rule: RuleId) -> list[str]:
    return [
        f"{case.id}[{engine}]"
        for case, engine in attack_runs()
        if case.rule is rule
        and demo_firewall()
        .check(case.sql, connection=connection_name(engine), profile=PROFILE)
        .allowed
    ]


@pytest.mark.parametrize("rule", LOAD_BEARING, ids=str)
def test_switching_the_rule_off_lets_an_attack_through(
    rule: RuleId,
    monkeypatch: pytest.MonkeyPatch,
):
    assert _through(rule) == []

    disable_rule(monkeypatch, rule)

    assert _through(rule) != [], f"no attack depends on {rule} alone"


@pytest.mark.parametrize("rule", sorted(SHADOWED), ids=str)
def test_shadowed_rule_is_still_shadowed(rule: RuleId, monkeypatch: pytest.MonkeyPatch):
    # If this fails, the rule became load-bearing: move it to LOAD_BEARING.
    disable_rule(monkeypatch, rule)

    assert _through(rule) == []
