"""Step 4: every table comes from the profile; catalogs and table functions never do."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope

from forbql.firewall._hints import nearest
from forbql.firewall._rule_id import RuleId
from forbql.firewall._verdict import Span, Violation

if TYPE_CHECKING:
    from forbql.firewall._context import CheckContext, Visibility


def check_objects(tree: exp.Expr, ctx: CheckContext) -> list[Violation]:
    """Check each table reference against the profile's visible tables.

    Runs before column qualification so that an unknown table is reported as a table.

    Args:
        tree: exp.Expr - The parsed tree.
        ctx: CheckContext - Inputs of the check; `visibility` is set.

    Returns:
        list[Violation] - Problems found.

    """
    visibility = ctx.visibility
    if visibility is None:
        return []
    cte_references: set[int] = set()
    for scope in traverse_scope(tree):
        cte_references.update(
            id(table)
            for table in scope.tables
            if not table.db and table.name in scope.cte_sources
        )
    violations: list[Violation] = []
    # Every Table node is checked, not only those scopes register as sources: a node the
    # scope analysis misses must not slip through.
    for table in tree.find_all(exp.Table):
        if id(table) not in cte_references:
            violation = _check_table(table, ctx, visibility)
            if violation is not None:
                violations.append(violation)
    return violations


def _check_table(
    table: exp.Table,
    ctx: CheckContext,
    visibility: Visibility,
) -> Violation | None:
    """Check one table reference.

    Args:
        table: exp.Table - The reference.
        ctx: CheckContext - Inputs of the check.
        visibility: Visibility - What the profile sees.

    Returns:
        Violation | None - The problem, or None when the table is visible.

    """
    if not isinstance(table.this, exp.Identifier):  # pyright: ignore[reportAny]
        function = table.this.sql(ctx.sqlglot_dialect)  # pyright: ignore[reportAny]
        return Violation(
            rule=RuleId.TABLE_FUNCTION,
            message=f"table functions are not allowed: {function}",
            span=Span.of(table.this),  # pyright: ignore[reportAny]
        )
    schema = table.db or visibility.default_schema
    name = f"{schema}.{table.name}"
    if schema in ctx.dialect.system_schemas or table.name.startswith(
        ctx.dialect.system_prefixes,
    ):
        return Violation(
            rule=RuleId.SYSTEM_CATALOG,
            message=f"system catalog {name} is not available",
            hint="use search_schema and describe_table to explore the schema",
            span=Span.of(table.this),
        )
    if table.catalog or name not in visibility.columns:
        # The same words for a hidden table and a missing one, so the caller cannot
        # probe which tables exist.
        return Violation(
            rule=RuleId.TABLE_NOT_ALLOWED,
            message=f"table {name} is not available",
            hint=nearest(name, visibility.columns, "tables"),
            span=Span.of(table.this),
        )
    return None
