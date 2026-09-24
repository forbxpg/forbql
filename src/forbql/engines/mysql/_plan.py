"""The cost of a MySQL plan, from either EXPLAIN FORMAT=JSON layout."""

from __future__ import annotations

_COST_KEYS = frozenset({"query_cost", "estimated_total_cost"})
"""Where the costs are: `query_cost` in layout 1, `estimated_total_cost` in 2."""


def plan_cost(plan: object) -> float | None:
    """Find the highest cost anywhere in the plan.

    The top of a plan carries the whole query's cost, except for a UNION in layout 1,
    which carries none: then its most expensive branch stands for it.

    Args:
        plan: object - The parsed JSON of EXPLAIN FORMAT=JSON.

    Returns:
        float | None - The cost; None if the plan carries none.

    """
    costs: list[float] = []
    pending = [plan]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            for key, value in node.items():  # pyright: ignore[reportUnknownVariableType]
                if key in _COST_KEYS and isinstance(value, str | int | float):
                    costs.append(float(value))
                else:
                    pending.append(value)  # pyright: ignore[reportUnknownArgumentType]
        elif isinstance(node, list):
            pending.extend(node)  # pyright: ignore[reportUnknownArgumentType]
    return max(costs, default=None)
