"""What `describe` asks MySQL, whose information schema shows only what one may use."""

from __future__ import annotations

COLUMNS = """
SELECT table_schema, table_name, column_name, column_type, is_nullable = 'YES',
       column_comment
FROM information_schema.columns
WHERE table_schema = DATABASE()
ORDER BY table_name, ordinal_position
"""
"""Columns the account may use, with their types and comments."""

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
