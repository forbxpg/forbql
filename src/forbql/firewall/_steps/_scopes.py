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
