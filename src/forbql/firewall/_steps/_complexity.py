"""Step 7: bounded joins and nesting; recursive CTEs only when the profile allows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlglot import exp

from forbql.firewall._rule_id import RuleId
from forbql.firewall._verdict import Violation

if TYPE_CHECKING:
    from forbql.firewall._context import CheckContext


def check_complexity(tree: exp.Expr, ctx: CheckContext) -> list[Violation]:
    """Count joins and SELECT nesting, and find recursive CTEs.

    Args:
        tree: exp.Expr - The tree.
        ctx: CheckContext - Inputs of the check.

    Returns:
        list[Violation] - Problems found.

    """
    violations: list[Violation] = []
    joins = sum(1 for _ in tree.find_all(exp.Join))
    max_joins = ctx.limits.max_joins
    if joins > max_joins:
        violations.append(
            Violation(
                rule=RuleId.TOO_MANY_JOINS,
                message=f"the query has {joins} joins, the limit is {max_joins}",
                hint="split the question into smaller queries",
            ),
        )
    depth = max(_select_depth(select) for select in tree.find_all(exp.Select))
    if depth > ctx.limits.max_subquery_depth:
        violations.append(
            Violation(
                rule=RuleId.SUBQUERY_TOO_DEEP,
                message=(
                    f"subqueries are nested {depth} deep, "
                    f"the limit is {ctx.limits.max_subquery_depth}"
                ),
                hint="flatten the query with joins or CTEs",
            ),
        )
    if not ctx.allow_recursive_cte and any(
        with_.recursive for with_ in tree.find_all(exp.With)
    ):
        violations.append(
            Violation(
                rule=RuleId.RECURSIVE_CTE,
                message="WITH RECURSIVE is not allowed for this profile",
                hint="rewrite without recursion",
            ),
        )
    return violations


def _select_depth(select: exp.Select) -> int:
    """Count the SELECTs enclosing a SELECT.

    Args:
        select: exp.Select - The SELECT.

    Returns:
        int - 0 for the outermost SELECT.

    """
    depth = 0
    parent = select.parent
    while parent is not None:
        if isinstance(parent, exp.Select):
            depth += 1
        parent = parent.parent
    return depth
