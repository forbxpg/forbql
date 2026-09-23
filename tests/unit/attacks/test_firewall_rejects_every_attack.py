"""The attack corpus against the firewall: every case is rejected by the rule it names."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from support.corpus import AttackCase, attack_runs, rules_of, run_id

if TYPE_CHECKING:
    from forbql import Engine


@pytest.mark.parametrize(
    ("case", "engine"),
    attack_runs(),
    ids=[run_id(run) for run in attack_runs()],
)
def test_attack_is_rejected_by_its_rule(case: AttackCase, engine: Engine):
    assert case.rule in rules_of(case.sql, engine)
