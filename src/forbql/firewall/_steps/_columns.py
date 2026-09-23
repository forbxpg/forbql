"""Step 3: every column resolves to a visible column; whole-row references never do."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlglot import exp
from sqlglot.errors import OptimizeError
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.qualify_columns import validate_qualify_columns
from sqlglot.optimizer.scope import Scope, traverse_scope

from forbql.firewall._hints import nearest
from forbql.firewall._rule_id import RuleId
from forbql.firewall._verdict import Span, Violation

from ._scopes import resolve_source

if TYPE_CHECKING:
    from collections.abc import Iterable

    from forbql.firewall._context import CheckContext, Visibility


def check_columns(
    tree: exp.Query,
    ctx: CheckContext,
) -> tuple[exp.Query, list[Violation]]:
    """Qualify every column against the visible schema; expand `*` to visible ones.

    Args:
        tree: exp.Query - The tree after the objects step.
        ctx: CheckContext - Inputs of the check; `visibility` is set.

    Returns:
        tuple[exp.Query, list[Violation]] - The qualified tree and the problems found.

    """
    visibility = ctx.visibility
    if visibility is None:
        return tree, []
    try:
        qualified = qualify(
            tree,
            dialect=ctx.sqlglot_dialect,
            db=visibility.default_schema,
            schema=visibility.sqlglot_schema(),
            # Leave unresolved columns in place so that this step reports them in its
            # own words, the same for a hidden column and a missing one.
            allow_partial_qualification=True,
            validate_qualify_columns=False,
        )
    except OptimizeError as error:
        return tree, [Violation(rule=RuleId.UNKNOWN_COLUMN, message=str(error))]
    violations = _whole_row_references(qualified)
    for scope in traverse_scope(qualified):
        violations.extend(_unresolved(scope, visibility))
    if not violations:
        try:
            qualified = validate_qualify_columns(qualified)
        except OptimizeError as error:
            violations.append(Violation(rule=RuleId.UNKNOWN_COLUMN, message=str(error)))
    return qualified, violations


def _whole_row_references(tree: exp.Expr) -> list[Violation]:
    """Reject `to_jsonb(t)`, `(t).column` and composite field access.

    A whole-row reference reads every column of a table, hidden ones included.

    Args:
        tree: exp.Expr - The qualified tree.

    Returns:
        list[Violation] - Problems found.

    """
    violations: list[Violation] = []
    for node in tree.walk():
        if isinstance(node, exp.TableColumn):
            violations.append(
                Violation(
                    rule=RuleId.WHOLE_ROW_REFERENCE,
                    message=f"whole-row reference to {node.name} is not allowed",
                    hint="name the columns you need",
                    span=Span.of(node),
                ),
            )
        elif isinstance(node, exp.Dot) and not isinstance(node.expression, exp.Func):  # pyright: ignore[reportAny]
            violations.append(
                Violation(
                    rule=RuleId.FIELD_ACCESS,
                    message=f"field access is not allowed: {node.sql()}",
                    hint="name table columns as table.column",
                ),
            )
    return violations


def _unresolved(scope: Scope, visibility: Visibility) -> list[Violation]:
    """Find columns of one scope that do not resolve to exactly one visible column.

    References to output aliases (`ORDER BY e`) are not in `Scope.columns`; the PII step
    finds them on its own.

    Args:
        scope: Scope - The scope.
        visibility: Visibility - What the profile sees.

    Returns:
        list[Violation] - Problems found.

    """
    violations: list[Violation] = []
    columns_by_source = {
        alias: _source_columns(source, visibility)
        for alias, source in scope.sources.items()
    }
    everything = [name for names in columns_by_source.values() for name in names]
    for column in scope.columns:
        if column.table:
            known = _source_columns(resolve_source(scope, column.table), visibility)
            if column.name not in known:
                written = f"{column.table}.{column.name}"
                violations.append(_unknown(column, written, known or everything))
            continue
        # The qualifier leaves a column unqualified when no source or several have it.
        owners = sorted(
            alias for alias, names in columns_by_source.items() if column.name in names
        )
        if len(owners) > 1:
            qualified = ", ".join(f"{owner}.{column.name}" for owner in owners)
            violations.append(
                Violation(
                    rule=RuleId.AMBIGUOUS_COLUMN,
                    message=f"column {column.name} is ambiguous",
                    hint=f"qualify it: {qualified}",
                    span=Span.of(column.this),  # pyright: ignore[reportAny]
                ),
            )
        else:
            violations.append(_unknown(column, column.name, everything))
    return violations


def _unknown(column: exp.Column, written: str, candidates: Iterable[str]) -> Violation:
    """Build the violation for a column that is hidden or does not exist.

    Args:
        column: exp.Column - The column.
        written: str - The column as the caller wrote it.
        candidates: Iterable[str] - Visible names to suggest from.

    Returns:
        Violation - The same words whether the column is hidden or missing.

    """
    return Violation(
        rule=RuleId.UNKNOWN_COLUMN,
        message=f"column {written} is not available",
        hint=nearest(column.name, candidates, "columns"),
        span=Span.of(column.this),  # pyright: ignore[reportAny]
    )


def _source_columns(
    source: exp.Table | Scope | None,
    visibility: Visibility,
) -> tuple[str, ...]:
    """Return the columns a source offers to the profile.

    Args:
        source: exp.Table | Scope | None - A base table, a derived table or CTE, or None
            for an alias that refers to nothing.
        visibility: Visibility - What the profile sees.

    Returns:
        tuple[str, ...] - Column names.

    """
    if isinstance(source, exp.Table):
        return visibility.columns.get(f"{source.db}.{source.name}", ())
    if isinstance(source, Scope):
        return _derived_columns(source)
    return ()


def _derived_columns(scope: Scope) -> tuple[str, ...]:
    """Return the output names of a derived table or CTE.

    Args:
        scope: Scope - Scope of the derived table.

    Returns:
        tuple[str, ...] - Output column names.

    """
    expression = scope.expression
    return tuple(expression.named_selects) if isinstance(expression, exp.Query) else ()
