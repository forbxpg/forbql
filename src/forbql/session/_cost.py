"""The planner's estimate against the profile's thresholds: run, confirm, or block."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from forbql.policy import ExplainThresholds


class CostDecision(StrEnum):
    """What the estimate decided; advisory, since hard bounds come from execution."""

    OK = "ok"
    CONFIRM = "confirm"
    BLOCK = "block"


COST_HINTS = {
    CostDecision.CONFIRM: (
        "the planner expects this query to be expensive; run it again confirmed"
    ),
    CostDecision.BLOCK: (
        "the planner expects this query to cost more than the profile allows; narrow it"
    ),
}
"""What the caller can do about a query the estimate stopped."""


def decide(
    cost: float | None,
    thresholds: ExplainThresholds,
    *,
    confirmed: bool,
) -> CostDecision:
    """Compare an estimate with the profile's thresholds.

    Args:
        cost: float | None - The estimate; None where the engine has none.
        thresholds: ExplainThresholds - The profile's thresholds.
        confirmed: bool - Whether the caller confirmed an expensive query.

    Returns:
        CostDecision - Block from `block_cost` on; from `confirm_cost` on, confirm
            unless confirmed; otherwise run.

    """
    if cost is None:
        return CostDecision.OK
    if cost >= thresholds.block_cost:
        return CostDecision.BLOCK
    if cost >= thresholds.confirm_cost and not confirmed:
        return CostDecision.CONFIRM
    return CostDecision.OK
