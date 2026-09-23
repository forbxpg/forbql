"""Step 6: PII columns appear only where their class allows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlglot import exp
from sqlglot.optimizer.scope import Scope, traverse_scope

from forbql.firewall._rule_id import RuleId
from forbql.firewall._verdict import ColumnMask, Span, Violation
from forbql.policy import PiiClass, PiiRule

from ._scopes import alias_references, resolve_source

if TYPE_CHECKING:
    from forbql.firewall._context import CheckContext, Visibility


def check_pii(
    tree: exp.Expr,
    ctx: CheckContext,
) -> tuple[list[ColumnMask], list[Violation]]:
    """Check PII placement and plan the masking of output columns.

    `mask`: a bare column in the outermost projection, masked on output.
    `aggregate_only`: the direct argument of `count()` or `count(DISTINCT)`. `deny`
    columns are not visible at all, so they never reach this step.

    Args:
        tree: exp.Expr - The qualified tree.
        ctx: CheckContext - Inputs of the check; `visibility` is set.

    Returns:
        tuple[list[ColumnMask], list[Violation]] - Masks by output position and
            problems.

    """
    visibility = ctx.visibility
    if visibility is None:
        return [], []
    masks: list[ColumnMask] = []
    violations: list[Violation] = []
    for scope in traverse_scope(tree):
        for column in scope.columns:
            mask, violation = _check_column(column, scope, visibility)
            if mask is not None:
                masks.append(mask)
            if violation is not None:
                violations.append(violation)
        for column in alias_references(scope):
            violation = _check_alias_reference(column, scope, visibility)
            if violation is not None:
                violations.append(violation)
    return masks, violations


def _check_column(
    column: exp.Column,
    scope: Scope,
    visibility: Visibility,
) -> tuple[ColumnMask | None, Violation | None]:
    """Check one column occurrence.

    Args:
        column: exp.Column - The column.
        scope: Scope - Its scope.
        visibility: Visibility - What the profile sees.

    Returns:
        tuple[ColumnMask | None, Violation | None] - The mask to apply and the problem;
            either may be None.

    """
    found = _pii_rule(column, scope, visibility)
    if found is None:
        return None, None
    source, rule = found
    if rule.pii_class is not PiiClass.MASK:
        if _inside_count(column):
            return None, None
        return None, Violation(
            rule=RuleId.PII_AGGREGATE_ONLY,
            message=f"column {source}.{column.name} can only be counted",
            hint=(
                f"count it with count(DISTINCT {column.name}); "
                "instead of SELECT *, list the columns you need"
            ),
            span=Span.of(column.this),  # pyright: ignore[reportAny]
        )
    position = _outer_projection_position(column, scope)
    if position is None or rule.strategy is None:
        return None, _masked_misuse(column, source)

    mask = ColumnMask(
        position=position,
        column=f"{source}.{column.name}",
        strategy=rule.strategy,
        keep_last=rule.keep_last,
    )
    return mask, None


def _pii_rule(
    column: exp.Column,
    scope: Scope,
    visibility: Visibility,
) -> tuple[str, PiiRule] | None:
    """Return the base table and PII rule of a column, if it is a PII column.

    Columns of derived tables are never PII here: a PII column inside a derived table's
    projection is itself outside the outermost projection and rejected there.

    Args:
        column: exp.Column - A qualified column.
        scope: Scope - Its scope.
        visibility: Visibility - What the profile sees.

    Returns:
        tuple[str, PiiRule] | None - `schema.table` and the rule, or None.

    """
    source = resolve_source(scope, column.table)
    if not isinstance(source, exp.Table):
        return None

    table = f"{source.db}.{source.name}"
    rule = visibility.pii.get((table, column.name))
    return None if rule is None else (table, rule)


def _outer_projection_position(column: exp.Column, scope: Scope) -> int | None:
    """Return the output position of a bare column of the outermost SELECT.

    Args:
        column: exp.Column - The column.
        scope: Scope - Its scope.

    Returns:
        int | None - Zero-based position, or None when the column is used any other way.

    """
    select = scope.expression
    if not scope.is_root or not isinstance(select, exp.Select):
        return None
    item = column.parent if isinstance(column.parent, exp.Alias) else column
    for position, projection in enumerate(select.expressions):  # pyright: ignore[reportAny]
        if projection is item:
            return position
    return None


def _inside_count(column: exp.Column) -> bool:
    """Tell whether a column is the direct argument of `count()` or `count(DISTINCT)`.

    Args:
        column: exp.Column - The column.

    Returns:
        bool - True when it is.

    """
    parent = column.parent
    if isinstance(parent, exp.Distinct):
        parent = parent.parent
    return isinstance(parent, exp.Count)


def _check_alias_reference(
    column: exp.Column,
    scope: Scope,
    visibility: Visibility,
) -> Violation | None:
    """Reject sorting or deduplicating by an output alias of a masked column.

    Args:
        column: exp.Column - A reference to an output alias.
        scope: Scope - Its scope.
        visibility: Visibility - What the profile sees.

    Returns:
        Violation | None - The problem, or None.

    """
    select = scope.expression
    if not isinstance(select, exp.Select):
        return None
    for projection in select.expressions:  # pyright: ignore[reportAny]
        target = projection.this if isinstance(projection, exp.Alias) else projection  # pyright: ignore[reportAny]
        if projection.alias_or_name == column.name and isinstance(target, exp.Column):
            found = _pii_rule(target, scope, visibility)
            if found is not None:
                return _masked_misuse(column, found[0], target.name)
    return None


def _masked_misuse(
    column: exp.Column,
    source: str,
    name: str | None = None,
) -> Violation:
    """Build the violation for a masked column used outside the outer projection.

    Args:
        column: exp.Column - Where it is used.
        source: str - Its table as `schema.table`.
        name: str | None - Its column name when `column` is an alias of it.

    Returns:
        Violation - The violation.

    """
    real = name or column.name
    return Violation(
        rule=RuleId.PII_MASKED,
        message=(
            f"masked column {source}.{real} can only be selected: not filtered, "
            "joined, sorted, grouped or passed to a function"
        ),
        hint=f"select {real} as a plain column of the outer SELECT; filter by others",
        span=Span.of(column.this),  # pyright: ignore[reportAny]
    )
