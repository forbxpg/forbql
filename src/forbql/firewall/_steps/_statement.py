"""Step 2: the root is a query and nothing inside writes, locks or reads variables."""

from __future__ import annotations

from sqlglot import exp
from sqlglot.expressions.dml import DML

from forbql.firewall._rule_id import RuleId
from forbql.firewall._verdict import Span, Violation

_WRITES: tuple[type[exp.Expr], ...] = (
    DML, exp.DDL, exp.Drop, exp.Alter, exp.TruncateTable, exp.Set, exp.Pragma,
    exp.Attach, exp.Detach, exp.Transaction, exp.Commit, exp.Rollback, exp.Grant,
    exp.Revoke, exp.Use, exp.Analyze, exp.Kill, exp.Execute, exp.Declare, exp.Cache,
    exp.Uncache, exp.Refresh,
)  # fmt: skip
_VARIABLES: tuple[type[exp.Expr], ...] = (
    exp.Parameter,
    exp.Placeholder,
    exp.SessionParameter,
    exp.PropertyEQ,
)


def check_statement(tree: exp.Expr) -> exp.Query | list[Violation]:
    """Accept SELECT, UNION, INTERSECT, EXCEPT and WITH over them, and nothing else.

    Args:
        tree: exp.Expr - The parsed tree.

    Returns:
        exp.Query | list[Violation] - The query, or problems found.

    """
    if not isinstance(tree, (exp.Select, exp.SetOperation)):
        return [
            Violation(
                rule=RuleId.NOT_A_QUERY,
                message=f"only SELECT queries are allowed, got {tree.key.upper()}",
                hint="send a SELECT; parentheses around the whole query are not needed",
            ),
        ]

    violations: list[Violation] = []
    for node in tree.walk():
        if isinstance(node, _WRITES):
            violations.append(
                Violation(
                    rule=RuleId.WRITE_OPERATION,
                    message=f"{node.key.upper()} is not allowed inside a query",
                    span=Span.of(node),
                ),
            )
        elif isinstance(node, exp.Into):
            violations.append(
                Violation(
                    rule=RuleId.SELECT_INTO,
                    message="SELECT INTO is not allowed",
                    hint="remove INTO",
                ),
            )
        elif isinstance(node, exp.Lock):
            violations.append(
                Violation(
                    rule=RuleId.ROW_LOCK,
                    message="row locks (FOR UPDATE, FOR SHARE) are not allowed",
                    hint="remove the FOR ... clause",
                ),
            )
        elif isinstance(node, _VARIABLES):
            violations.append(
                Violation(
                    rule=RuleId.VARIABLE,
                    message=f"parameters and variables are not allowed: {node.sql()}",
                    hint="write values as literals",
                    span=Span.of(node),
                ),
            )
    return violations or tree
