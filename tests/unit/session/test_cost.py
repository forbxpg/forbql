from __future__ import annotations

import pytest

from forbql.policy import ExplainThresholds
from forbql.session import CostDecision
from forbql.session._cost import decide

THRESHOLDS = ExplainThresholds(confirm_cost=100, block_cost=1000)


@pytest.mark.parametrize(
    ("cost", "confirmed", "decision"),
    [
        (None, False, CostDecision.OK),
        (99.9, False, CostDecision.OK),
        (100, False, CostDecision.CONFIRM),
        (100, True, CostDecision.OK),
        (999.9, True, CostDecision.OK),
        (1000, False, CostDecision.BLOCK),
        (1000, True, CostDecision.BLOCK),
    ],
)
def test_the_estimate_decides_by_the_thresholds(
    cost: float | None,
    confirmed: bool,  # ruff: ignore[boolean-type-hint-positional-argument]
    decision: CostDecision,
):
    assert decide(cost, THRESHOLDS, confirmed=confirmed) is decision
