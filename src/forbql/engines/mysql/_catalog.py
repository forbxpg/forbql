"""What `describe` asks MySQL, whose information schema shows only what one may use."""

from __future__ import annotations

from forbql.firewall import ColumnInfo

COLUMNS = """
SELECT table_schema, table_name, column_name, column_type, is_nullable = 'YES',
       column_comment,
       extra LIKE '%VIRTUAL GENERATED%' OR extra LIKE '%STORED GENERATED%',
       CASE
           WHEN extra LIKE '%VIRTUAL GENERATED%'
             OR extra LIKE '%STORED GENERATED%'
           THEN NULLIF(generation_expression, '')
       END
FROM information_schema.columns
WHERE table_schema = DATABASE()
ORDER BY table_name, ordinal_position
"""
"""Columns the account may use, with their types, comments and generation expressions.

An expression default (`DEFAULT_GENERATED`) is not a generated column. An empty
generation expression stays null, so the firewall hides the column.
"""

RELATIONS = """
SELECT t.table_schema, t.table_name, t.table_comment, t.table_type = 'VIEW',
       v.view_definition
FROM information_schema.tables AS t
     LEFT JOIN information_schema.views AS v
     ON v.table_schema = t.table_schema AND v.table_name = t.table_name
WHERE t.table_schema = DATABASE()
"""
"""Comments of tables and views; views' definitions, empty without SHOW VIEW."""

KEYS = """
SELECT table_schema, table_name, constraint_name, column_name,
       referenced_table_schema, referenced_table_name, referenced_column_name
FROM information_schema.key_column_usage
WHERE table_schema = DATABASE()
  AND (constraint_name = 'PRIMARY' OR referenced_table_name IS NOT NULL)
ORDER BY table_name, constraint_name, ordinal_position
"""
"""Primary and foreign keys, one row per column."""


def column_info(
    name: str,
    kind: str,
    comment: str | None,
    *,
    nullable: bool | int,
    generation: tuple[bool | int, str | None] = (False, None),
) -> ColumnInfo:
    """Build a column from one information-schema row.

    A generated column with no expression stays generated, so the firewall hides
    it. A stored column drops any expression, so an expression default is not
    generation. The flag may be the 0 or 1 MySQL returns for a boolean.

    Args:
        name: str - Column name.
        kind: str - Type as MySQL names it.
        comment: str | None - The column's comment; empty becomes None.
        nullable: bool | int - Whether the column may hold NULL.
        generation: tuple[bool | int, str | None] - Whether `EXTRA` names a
            generated column, and `GENERATION_EXPRESSION` when one was read.

    Returns:
        ColumnInfo - The column.

    """
    generated, expression = generation
    is_generated = bool(generated)
    return ColumnInfo(
        name=name,
        type=kind,
        nullable=bool(nullable),
        comment=comment or None,
        generated=is_generated,
        expression=_expression(expression) if is_generated else None,
    )


def _expression(expression: str | None) -> str | None:
    """Return a generation expression, or None when it was not readable.

    Args:
        expression: str | None - `GENERATION_EXPRESSION`, or None.

    Returns:
        str | None - The stripped expression, or None when it is missing or blank.

    """
    if not isinstance(expression, str):
        return None
    return expression.strip() or None
