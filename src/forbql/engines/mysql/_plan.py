"""The cost of a MySQL plan, from either EXPLAIN FORMAT=JSON layout."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Iterable


def plan_cost(plan: object) -> float | None:
    """Find the cost of the whole query in its plan.

    A plan's top carries the whole query's cost: `estimated_total_cost` in layout 2,
    `cost_info.query_cost` of the query block in layout 1. A UNION in layout 1 carries
    none, so its branches' costs are added up.

    Args:
        plan: object - The parsed JSON of EXPLAIN FORMAT=JSON, or a part of it.

    Returns:
        float | None - The cost; None if the plan carries none.

    """
    if isinstance(plan, list):
        return _highest(plan_cost(item) for item in cast("list[object]", plan))
    if not isinstance(plan, dict):
        return None
    node = cast("dict[str, object]", plan)
    if (own := _own_cost(node)) is not None:
        return own
    union = node.get("union_result")
    if isinstance(union, dict):
        branches = cast("dict[str, object]", union).get("query_specifications", [])
        parts = [plan_cost(branch) for branch in cast("list[object]", branches)]
        known = [part for part in parts if part is not None]
        return sum(known) if known else None
    return _highest(plan_cost(value) for value in node.values())


def _own_cost(node: dict[str, object]) -> float | None:
    """Read the cost a node states for itself.

    Args:
        node: dict[str, object] - A part of the plan.

    Returns:
        float | None - The cost; None if the node states none.

    """
    cost = node.get("estimated_total_cost")
    info = node.get("cost_info")
    if cost is None and isinstance(info, dict):
        cost = cast("dict[str, object]", info).get("query_cost")
    return float(cost) if isinstance(cost, str | int | float) else None


def _highest(costs: Iterable[float | None]) -> float | None:
    """Take the highest of the costs found below a node.

    Args:
        costs: Iterable[float | None] - Costs, None where a part has none.

    Returns:
        float | None - The highest; None if none has a cost.

    """
    return max((cost for cost in costs if cost is not None), default=None)
