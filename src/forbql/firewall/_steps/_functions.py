"""Step 5: allowlisted functions called by their plain names; built-in casts only."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlglot import exp

from forbql.firewall._hints import nearest
from forbql.firewall._rule_id import RuleId
from forbql.firewall._verdict import Span, Violation

if TYPE_CHECKING:
    from forbql.firewall._context import CheckContext


def function_name(node: exp.Func) -> str:
    """Return the name a function is really called by, upper case.

    `Func.name` returns the name of the first argument, so it is never used here.

    Args:
        node: exp.Func - The call.

    Returns:
        str - The name.

    """
    if isinstance(node, exp.Anonymous):
        return str(node.this).upper()  # pyright: ignore[reportAny]
    return node.sql_name().upper()


def check_functions(tree: exp.Expr, ctx: CheckContext) -> list[Violation]:
    """Check every call, cast and operator against the allowlists.

    Args:
        tree: exp.Expr - The tree.
        ctx: CheckContext - Inputs of the check.

    Returns:
        list[Violation] - Problems found.

    """
    violations: list[Violation] = []
    for node in tree.walk():
        if isinstance(node, exp.Operator):
            violations.append(
                Violation(
                    rule=RuleId.OPERATOR_SYNTAX,
                    message="OPERATOR(...) syntax is not allowed",
                    hint="write the operator directly",
                ),
            )
        elif isinstance(node, exp.Cast) and node.to.this not in ctx.dialect.cast_types:  # pyright: ignore[reportAny]
            target = node.to.sql(ctx.sqlglot_dialect)
            violations.append(
                Violation(
                    rule=RuleId.CAST_NOT_ALLOWED,
                    message=f"cast to {target} is not allowed",
                    hint="cast to a built-in numeric, text, date or time type",
                    span=Span.of(node.to),
                ),
            )
        elif isinstance(node, exp.Func) and not isinstance(node, exp.Connector):
            violation = _check_call(node, ctx)
            if violation is not None:
                violations.append(violation)
    return violations


def _check_call(node: exp.Func, ctx: CheckContext) -> Violation | None:
    """Check one function call.

    Args:
        node: exp.Func - The call.
        ctx: CheckContext - Inputs of the check.

    Returns:
        Violation | None - The problem, or None when the call is allowed.

    """
    name = function_name(node)
    if isinstance(node.parent, exp.Dot) and node.arg_key == "expression":
        call = node.parent.sql(ctx.sqlglot_dialect)
        return Violation(
            rule=RuleId.QUALIFIED_FUNCTION,
            message=f"schema-qualified call {call} is not allowed",
            hint=f"call {name.lower()}(...) without a schema"
            if name in ctx.functions
            else None,
            span=Span.of(node),
        )
    if name not in ctx.functions:
        return Violation(
            rule=RuleId.FUNCTION_NOT_ALLOWED,
            message=f"function {name.lower()} is not allowed",
            hint=nearest(
                name.lower(),
                (allowed.lower() for allowed in ctx.functions),
                "functions",
            ),
            span=Span.of(node),
        )
    return None
