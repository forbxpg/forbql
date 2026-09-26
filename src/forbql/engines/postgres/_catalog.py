"""What `describe` asks PostgreSQL's catalog, with `search_path` set to `pg_catalog`."""

from __future__ import annotations

COLUMNS = """
SELECT n.nspname, c.relname, a.attname, format_type(a.atttypid, a.atttypmod),
       NOT a.attnotnull, col_description(c.oid, a.attnum)
FROM pg_attribute a
     JOIN pg_class c ON c.oid = a.attrelid
     JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p', 'v', 'f') AND a.attnum > 0 AND NOT a.attisdropped
  AND n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg\\_%'
  AND has_column_privilege(c.oid, a.attnum, 'SELECT')
ORDER BY n.nspname, c.relname, a.attnum
"""
"""Columns the role may read, with their types and comments."""

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
