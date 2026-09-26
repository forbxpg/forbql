"""What the startup check asks PostgreSQL about the role; each row is one finding.

The queries run with `search_path` set to `pg_catalog`, so a role cannot shadow the
catalogs it is asked about. Schemas named `pg_*` and `information_schema` belong to
the server and are skipped.
"""

from __future__ import annotations

ATTRIBUTES = """
SELECT 'the role has ' || a.attribute
FROM pg_roles r,
     LATERAL (VALUES ('SUPERUSER', r.rolsuper), ('BYPASSRLS', r.rolbypassrls),
                     ('CREATEROLE', r.rolcreaterole), ('CREATEDB', r.rolcreatedb),
                     ('REPLICATION', r.rolreplication)) AS a (attribute, granted)
WHERE r.rolname = current_user AND a.granted
"""
"""Role attributes that are refused; a superuser needs no further questions."""

MEMBERSHIPS = """
SELECT 'the role is a member of ' || quote_ident(g.rolname)
FROM pg_auth_members m
     JOIN pg_roles g ON g.oid = m.roleid
     JOIN pg_roles r ON r.oid = m.member
WHERE r.rolname = current_user AND g.rolname <> 'pg_read_all_data'
"""

TABLE_WRITES = """
SELECT 'the role may ' || p.privilege || ' on '
       || quote_ident(n.nspname) || '.' || quote_ident(c.relname)
FROM pg_class c
     JOIN pg_namespace n ON n.oid = c.relnamespace,
     unnest(ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER']
            || CASE WHEN current_setting('server_version_num')::int >= 170000
                    THEN ARRAY['MAINTAIN'] ELSE ARRAY[]::text[] END) AS p (privilege)
WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg\\_%'
  AND has_table_privilege(c.oid, p.privilege)
"""

COLUMN_WRITES = """
SELECT 'the role may ' || p.privilege || ' on '
       || quote_ident(n.nspname) || '.' || quote_ident(c.relname)
       || ' (' || quote_ident(a.attname) || ')'
FROM pg_attribute a
     JOIN pg_class c ON c.oid = a.attrelid
     JOIN pg_namespace n ON n.oid = c.relnamespace,
     unnest(ARRAY['INSERT', 'UPDATE', 'REFERENCES']) AS p (privilege)
WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg\\_%'
  AND a.attnum > 0 AND NOT a.attisdropped
  AND NOT has_table_privilege(c.oid, p.privilege)
  AND has_column_privilege(c.oid, a.attnum, p.privilege)
"""

OWNERSHIP = """
SELECT 'the role owns ' || quote_ident(n.nspname) || '.' || quote_ident(c.relname)
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)
  AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
  AND n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg\\_%'
UNION ALL
SELECT 'the role owns schema ' || quote_ident(n.nspname)
FROM pg_namespace n
WHERE n.nspowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)
  AND n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg\\_%'
UNION ALL
SELECT 'the role owns function ' || p.oid::regprocedure
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE p.proowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)
  AND n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg\\_%'
UNION ALL
SELECT 'the role owns database ' || quote_ident(datname)
FROM pg_database
WHERE datname = current_database()
  AND datdba = (SELECT oid FROM pg_roles WHERE rolname = current_user)
"""

SCHEMA_CREATE = """
SELECT 'the role may CREATE in schema ' || quote_ident(n.nspname)
FROM pg_namespace n
WHERE n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg\\_%'
  AND has_schema_privilege(n.oid, 'CREATE')
"""

DATABASE_CREATE = """
SELECT 'the role may CREATE schemas in database ' || quote_ident(current_database())
WHERE has_database_privilege(current_database(), 'CREATE')
"""

SEQUENCES = """
SELECT 'the role may use sequence '
       || quote_ident(n.nspname) || '.' || quote_ident(c.relname)
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'S'
  AND n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg\\_%'
  -- has_sequence_privilege raises on a relation that is not a sequence, and the
  -- planner may call it before it filters by relkind.
  AND CASE WHEN c.relkind = 'S'
           THEN has_sequence_privilege(c.oid, 'USAGE')
                OR has_sequence_privilege(c.oid, 'UPDATE')
           ELSE false END
"""

USER_MAPPINGS = """
SELECT 'the role may reach foreign server ' || quote_ident(srvname)
       || ' through a user mapping'
FROM pg_user_mappings
WHERE usename IN (current_user, 'public')
"""

STRING_LITERALS = """
SELECT 'standard_conforming_strings is off: the server reads string literals '
       || 'differently from the firewall'
WHERE current_setting('standard_conforming_strings') <> 'on'
"""

REFUSALS = (
    MEMBERSHIPS,
    TABLE_WRITES,
    COLUMN_WRITES,
    OWNERSHIP,
    SCHEMA_CREATE,
    DATABASE_CREATE,
    SEQUENCES,
    USER_MAPPINGS,
    STRING_LITERALS,
)
"""Findings that stop forbql from starting, after the role attributes."""

TEMPORARY = """
SELECT 'the role may create temporary tables: REVOKE TEMPORARY ON DATABASE '
       || quote_ident(current_database()) || ' FROM PUBLIC, '
       || quote_ident(current_user) || ';'
WHERE has_database_privilege(current_database(), 'TEMPORARY')
"""

SECURITY_DEFINER = """
SELECT 'the role may execute SECURITY DEFINER function ' || p.oid::regprocedure
       || ': REVOKE EXECUTE ON FUNCTION ' || p.oid::regprocedure || ' FROM PUBLIC;'
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE p.prosecdef
  AND n.nspname <> 'information_schema' AND n.nspname NOT LIKE 'pg\\_%'
  AND has_function_privilege(p.oid, 'EXECUTE')
"""

WARNINGS = (TEMPORARY, SECURITY_DEFINER)
"""Findings worth revoking that break no guarantee: PUBLIC holds them by default."""
