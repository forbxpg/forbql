"""Step 8: the outermost query returns at most `max_rows` rows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlglot import exp

from forbql.firewall._rule_id import RuleId
from forbql.firewall._verdict import Violation

if TYPE_CHECKING:
    from forbql.firewall._context import CheckContext


def enforce_limit(
    tree: exp.Query,
    ctx: CheckContext,
) -> tuple[exp.Query, list[str], list[Violation]]:
    """Add a LIMIT, or lower one above `max_rows`.

    Args:
        tree: exp.Query - The checked tree.
        ctx: CheckContext - Inputs of the check.

    Returns:
        tuple[exp.Query, list[str], list[Violation]] - The tree, the rewrites made, and
            problems found.

    """
    max_rows = ctx.limits.max_rows
    limit = tree.args.get("limit")
    if limit is None:
        return tree.limit(max_rows), [f"added LIMIT {max_rows}"], []
    value = limit.expression if isinstance(limit, exp.Limit) else None  # pyright: ignore[reportAny]
    if not isinstance(value, exp.Literal) or not value.is_int:
        return (
            tree,
            [],
            [
                Violation(
                    rule=RuleId.INVALID_LIMIT,
                    message="LIMIT must be a whole number literal",
                    hint=f"write LIMIT n with n up to {max_rows}",
                ),
            ],
        )
    rows = int(value.name)
    if rows <= max_rows:
        return tree, [], []
    return tree.limit(max_rows), [f"lowered LIMIT {rows} to {max_rows}"], []
