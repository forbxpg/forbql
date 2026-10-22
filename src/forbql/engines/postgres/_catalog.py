"""What `describe` asks PostgreSQL's catalog, with `search_path` set to `pg_catalog`."""

from __future__ import annotations

from forbql.firewall import ColumnInfo

COLUMNS = """
SELECT n.nspname, c.relname, a.attname, format_type(a.atttypid, a.atttypmod),
       NOT a.attnotnull, col_description(c.oid, a.attnum),
       a.attgenerated IN ('s', 'v'),
       CASE WHEN a.attgenerated IN ('s', 'v') THEN (
           SELECT pg_get_expr(ad.adbin, ad.adrelid)
           FROM pg_attrdef ad
           WHERE ad.adrelid = a.attrelid AND ad.adnum = a.attnum
       ) END
FROM pg_attribute a
     JOIN pg_class c ON c.oid = a.attrelid
     JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p', 'v', 'f') AND a.attnum > 0 AND NOT a.attisdropped
  AND n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg\\_%'
  AND has_column_privilege(c.oid, a.attnum, 'SELECT')
ORDER BY n.nspname, c.relname, a.attnum
"""
"""Columns the role may read, with their types, comments and generation expressions.

`attgenerated` is `s` or `v` for a generated column. The expression is read only
then, so a column default is not taken for one. No `pg_attrdef` row leaves the
expression null: the column stays generated and the firewall hides it.
"""

RELATIONS = """
SELECT n.nspname, c.relname, obj_description(c.oid, 'pg_class'), c.relkind = 'v',
       CASE WHEN c.relkind = 'v' THEN pg_get_viewdef(c.oid) END
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p', 'v', 'f')
  AND n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg\\_%'
"""
"""Comments of tables and views, and the views' definitions."""

KEYS = """
SELECT n.nspname, c.relname, k.contype::text,
       ARRAY(SELECT a.attname FROM unnest(k.conkey) WITH ORDINALITY AS u (attnum, i)
             JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = u.attnum
             ORDER BY u.i),
       fn.nspname, fc.relname,
       ARRAY(SELECT a.attname FROM unnest(k.confkey) WITH ORDINALITY AS u (attnum, i)
             JOIN pg_attribute a ON a.attrelid = k.confrelid AND a.attnum = u.attnum
             ORDER BY u.i)
FROM pg_constraint k
     JOIN pg_class c ON c.oid = k.conrelid
     JOIN pg_namespace n ON n.oid = c.relnamespace
     LEFT JOIN pg_class fc ON fc.oid = k.confrelid
     LEFT JOIN pg_namespace fn ON fn.oid = fc.relnamespace
WHERE k.contype IN ('p', 'f')
  AND n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg\\_%'
ORDER BY k.conname
"""
"""Primary and foreign keys; `contype` is cast, as asyncpg reads `"char"` as bytes.

`assemble` drops the keys that name what the role cannot read.
"""


def column_info(
    name: str,
    kind: str,
    comment: str | None,
    *,
    nullable: bool,
    generation: tuple[bool, str | None] = (False, None),
) -> ColumnInfo:
    """Build a column from one catalog row.

    A generated column with no expression stays generated, so the firewall hides
    it. A stored column drops any expression, so a default is not generation.

    Args:
        name: str - Column name.
        kind: str - Type as PostgreSQL names it.
        comment: str | None - The column's comment.
        nullable: bool - Whether the column may hold NULL.
        generation: tuple[bool, str | None] - Whether the column is generated,
            and the expression when one was read.

    Returns:
        ColumnInfo - The column.

    """
    generated, expression = generation
    return ColumnInfo(
        name=name,
        type=kind,
        nullable=nullable,
        comment=comment,
        generated=generated,
        expression=_expression(expression) if generated else None,
    )


def _expression(expression: str | None) -> str | None:
    """Return a generation expression, or None when it was not readable.

    Args:
        expression: str | None - Text from `pg_get_expr`, or None.

    Returns:
        str | None - The stripped expression, or None when it is missing or blank.

    """
    if expression is None:
        return None
    return expression.strip() or None
