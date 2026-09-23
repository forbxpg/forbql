"""Resolving column qualifiers to what they refer to."""

from __future__ import annotations

from sqlglot import exp
from sqlglot.optimizer.scope import Scope


def resolve_source(scope: Scope, alias: str) -> exp.Table | Scope | None:
    """Find what a table alias refers to, looking outward for correlated references.

    Args:
        scope: Scope - The scope where the column appears.
        alias: str - The table alias the column is qualified with.

    Returns:
        exp.Table | Scope | None - A base table, a derived table or CTE, or None.

    """
    current: Scope | None = scope
    while current is not None:
        source = current.sources.get(alias)
        if isinstance(source, (exp.Table, Scope)):
            return source
        current = current.parent
    return None


def alias_references(scope: Scope) -> list[exp.Column]:
    """Return columns of a SELECT that name one of its own output aliases.

    `ORDER BY e` and `ORDER BY 1` both end up here after qualification. Scope analysis
    leaves them out of `Scope.columns`, so they are found by walking the SELECT. Every
    other column is qualified by then, so an unqualified one is an alias reference.

    Args:
        scope: Scope - The scope.

    Returns:
        list[exp.Column] - The alias references.

    """
    select = scope.expression
    if not isinstance(select, exp.Select):
        return []
    aliases = {item.alias_or_name for item in select.expressions}  # pyright: ignore[reportAny]
    return [
        column
        for column in select.find_all(exp.Column)
        if not column.table
        and column.name in aliases
        and column.find_ancestor(exp.Select) is select
    ]
