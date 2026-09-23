"""Per-engine facts the rules need: system objects, built-in allowlists."""

from __future__ import annotations

from dataclasses import dataclass

from sqlglot import exp

from forbql.policy import Engine

# Canonical sqlglot names (`sql_name()`), so one name covers every spelling a dialect
# parses into it. Functions that read files, sleep, lock, change settings, run SQL from
# a string or build unbounded strings are absent on purpose.
_COMMON_FUNCTIONS = frozenset({
    "ABS", "AVG", "CASE", "CAST", "CEIL", "COALESCE", "CONCAT", "COUNT", "CURRENT_DATE",
    "CURRENT_TIMESTAMP", "DATE_TRUNC", "DATEDIFF", "DENSE_RANK", "EXISTS", "EXTRACT",
    "FLOOR", "GREATEST", "IF", "LAG", "LEAD", "LEAST", "LENGTH", "LOWER", "MAX", "MIN",
    "NULLIF", "POW", "RANK", "REPLACE", "ROUND", "ROW_NUMBER", "SUBSTRING", "SUM",
    "TIME_TO_STR", "TIMESTAMP_TRUNC", "TRIM", "TRY_CAST", "TS_OR_DS_TO_DATE",
    "TS_OR_DS_TO_TIMESTAMP", "UPPER",
})  # fmt: skip

_CAST_TYPES = frozenset({
    exp.DType.BIGINT, exp.DType.BOOLEAN, exp.DType.CHAR,
    exp.DType.DATE, exp.DType.DATETIME, exp.DType.DECIMAL,
    exp.DType.DOUBLE, exp.DType.FLOAT, exp.DType.INT,
    exp.DType.INTERVAL, exp.DType.SMALLINT, exp.DType.TEXT,
    exp.DType.TIME, exp.DType.TIMESTAMP, exp.DType.TIMESTAMPTZ,
    exp.DType.TINYINT, exp.DType.UBIGINT, exp.DType.UUID,
    exp.DType.VARCHAR,
})  # fmt: skip


@dataclass(frozen=True, slots=True, kw_only=True)
class DialectProfile:
    """What the firewall must know about one engine.

    Attributes:
        engine: Engine - The engine; its value is also the sqlglot dialect name.
        system_schemas: frozenset[str] - Schemas holding catalogs and settings.
        system_prefixes: tuple[str, ...] - Prefixes of system table names.
        functions: frozenset[str] - Built-in allowlist, upper case.
        cast_types: frozenset[exp.DType] - Types a cast may target.

    """

    engine: Engine
    system_schemas: frozenset[str]
    system_prefixes: tuple[str, ...]
    functions: frozenset[str]
    cast_types: frozenset[exp.DType] = _CAST_TYPES


DIALECTS: dict[Engine, DialectProfile] = {
    Engine.POSTGRES: DialectProfile(
        engine=Engine.POSTGRES,
        system_schemas=frozenset(
            {"pg_catalog", "information_schema", "pg_toast"},
        ),
        system_prefixes=("pg_",),
        functions=_COMMON_FUNCTIONS,
    ),
    Engine.MYSQL: DialectProfile(
        engine=Engine.MYSQL,
        system_schemas=frozenset({
            "mysql",
            "information_schema",
            "performance_schema",
            "sys",
        }),
        system_prefixes=(),
        functions=_COMMON_FUNCTIONS | {"DAY", "MONTH", "NOW", "YEAR"},
    ),
    Engine.SQLITE: DialectProfile(
        engine=Engine.SQLITE,
        system_schemas=frozenset({"temp"}),
        system_prefixes=("sqlite_",),
        functions=_COMMON_FUNCTIONS | {"DATE", "DATETIME", "JULIANDAY"},
    ),
}
