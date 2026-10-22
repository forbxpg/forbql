"""SQLite has no roles, so every read and call is checked at prepare time."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from sqlite3 import (
    SQLITE_DENY,
    SQLITE_FUNCTION,
    SQLITE_OK,
    SQLITE_READ,
    SQLITE_RECURSIVE,
    SQLITE_SELECT,
)
from typing import TYPE_CHECKING

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

if TYPE_CHECKING:
    from forbql.engines._protocol import Restriction

BUILTIN_FUNCTIONS = frozenset({
    "abs", "avg", "ceil", "ceiling", "coalesce", "concat", "count", "date", "datetime",
    "dense_rank", "floor", "glob", "ifnull", "iif", "instr", "julianday", "lag", "lead",
    "length", "like", "lower", "ltrim", "max", "min", "nullif", "pow", "power", "rank",
    "replace", "round", "row_number", "rtrim", "strftime", "substr", "substring", "sum",
    "time", "total", "trim", "unixepoch", "upper",
})  # fmt: skip
"""
SQLite's own names for the firewall's built-in allowlist, plus the functions SQLite
calls implicitly (LIKE, GLOB) and the window functions.
"""

type Authorizer = Callable[[int, str | None, str | None, str | None, str | None], int]
type Expressions = Mapping[str, Mapping[str, str | None]]

_DIALECTS = ("postgres", "mysql", "sqlite")


class _Ordinary:
    """A column the catalog did not record as generated."""


_ORDINARY = _Ordinary()


@dataclass(frozen=True, slots=True)
class _Scope:
    """What one authorizer compares a read against.

    Attributes:
        columns: dict[str, frozenset[str]] - Visible columns per `schema.table`.
        stored: frozenset[str] - Names of every stored table and view.
        generated: Expressions - Generation expressions by `schema.table`.

    """

    columns: dict[str, frozenset[str]]
    stored: frozenset[str]
    generated: Expressions


def authorizer(
    restriction: Restriction,
    stored: frozenset[str],
    generated: Expressions | None = None,
) -> Authorizer:
    """Build an authorizer that allows only the profile's reads and calls.

    A generated column is denied when its expression cannot be read or parsed, or
    when it reads a column this same authorizer would deny.

    Args:
        restriction: Restriction - What the profile may touch.
        stored: frozenset[str] - Names of every table and view in the file.
        generated: Expressions | None - Generation expression per `schema.table`
            and column. None for a column means the expression could not be read.

    Returns:
        Authorizer - The callback for `sqlite3.Connection.set_authorizer`.

    """
    columns = {table: frozenset(names) for table, names in restriction.tables.items()}
    scope = _Scope(columns=columns, stored=stored, generated=generated or {})
    funcs = BUILTIN_FUNCTIONS | {name.lower() for name in restriction.functions}

    def _check(
        action: int,
        first: str | None,
        second: str | None,
        db: str | None,
        _trigger: str | None,
    ) -> int:
        allowed = False
        if action == SQLITE_SELECT:
            allowed = True
        elif action == SQLITE_READ:
            allowed = _read(scope, first or "", second or "", db)
        elif action == SQLITE_FUNCTION:
            allowed = (second or "").lower() in funcs
        elif action == SQLITE_RECURSIVE:
            allowed = restriction.allow_recursive
        return SQLITE_OK if allowed else SQLITE_DENY

    return _check


def _read(
    scope: _Scope,
    table: str,
    column: str,
    database: str | None,
    seen: frozenset[tuple[str, str, str]] | None = None,
) -> bool:
    """Tell whether the profile may read a table, or one column of it.

    SQLite leaves the database out for reads of a CTE and for whole-table reads
    (count(*)) of a table named without its schema. A name that is not a stored
    table is a CTE, whose own reads were authorized one by one.

    Args:
        scope: _Scope - Columns, stored names and generation expressions.
        table: str - Table the read names.
        column: str - Column the read names; empty for a whole-table read.
        database: str | None - Database the read names, when SQLite reports one.
        seen: frozenset[tuple[str, str, str]] | None - Generated columns already
            entered, so a cycle is denied. None at the first read.

    Returns:
        bool - True when the read is allowed.

    """
    if seen is None:
        seen = frozenset[tuple[str, str, str]]()
    if database is None and table not in scope.stored:
        return True
    if not _listed(scope, table, column, database):
        return False
    if not column:
        return True
    return _generated_allowed(scope, table, column, database, seen)


def _listed(scope: _Scope, table: str, column: str, database: str | None) -> bool:
    """Tell whether the profile lists a table, and this column when one is named.

    Args:
        scope: _Scope - Columns the profile may read.
        table: str - Table the read names.
        column: str - Column the read names; empty for a whole-table read.
        database: str | None - Database the read names.

    Returns:
        bool - True when the read names something listed.

    """
    visible = scope.columns.get(f"{database or 'main'}.{table}")
    return visible is not None and (not column or column in visible)


def _generated_allowed(
    scope: _Scope,
    table: str,
    column: str,
    database: str | None,
    seen: frozenset[tuple[str, str, str]],
) -> bool:
    """Tell whether a generated column's expression reads only allowed columns.

    An ordinary column is allowed. A missing or unparseable expression is not.

    Args:
        scope: _Scope - Generation expressions and the columns they may read.
        table: str - Table the read names.
        column: str - Column the read names.
        database: str | None - Database the read names.
        seen: frozenset[tuple[str, str, str]] - Generated columns already entered.

    Returns:
        bool - True when the column may be read.

    """
    identity = (database or "main", table, column)
    if identity in seen:
        return False
    expression = _expression(scope.generated, f"{identity[0]}.{table}", column)
    sources = _sources(expression)
    if sources is None:
        return expression is _ORDINARY
    return all(
        _read(
            scope,
            source_table or table,
            source_column,
            source_schema or database,
            seen | {identity},
        )
        for source_schema, source_table, source_column in sources
    )


def _sources(
    expression: str | _Ordinary | None,
) -> tuple[tuple[str, str, str], ...] | None:
    """Parse a generation expression into the columns it reads.

    Args:
        expression: str | _Ordinary | None - The expression, `_ORDINARY` for a
            stored column, or None when the expression could not be read.

    Returns:
        tuple[tuple[str, str, str], ...] | None - The references, or None when
            there is nothing to walk.

    """
    if not isinstance(expression, str) or not expression.strip():
        return None
    return _source_columns(expression)


def _expression(
    generated: Expressions,
    table: str,
    column: str,
) -> str | _Ordinary | None:
    """Return a generated column's expression, or `_ORDINARY` when it is stored.

    Args:
        generated: Expressions - Generation expressions by `schema.table`.
        table: str - Table as `schema.table`.
        column: str - Column name as SQLite reports it.

    Returns:
        str | _Ordinary | None - The expression, `_ORDINARY` when the column is
            not generated, or None when the expression cannot be read.

    """
    columns = generated.get(table)
    if columns is None:
        return _ORDINARY
    for name, expression in columns.items():
        if name.lower() == column.lower():
            return expression
    return _ORDINARY


def _source_columns(expression: str) -> tuple[tuple[str, str, str], ...] | None:
    """Find columns a generation expression reads.

    Args:
        expression: str - The generation expression.

    Returns:
        tuple[tuple[str, str, str], ...] | None - `(schema, table, column)` for
            each reference, with schema and table empty when unqualified. None
            when the expression cannot be parsed or contains a star.

    """
    found: dict[tuple[str, str, str], tuple[str, str, str]] = {}
    parsed = False
    for dialect in _DIALECTS:
        try:
            tree = sqlglot.parse_one(expression, read=dialect)
        except SqlglotError:
            continue
        parsed = True
        if next(tree.find_all(exp.Star), None) is not None:
            return None
        for column in tree.find_all(exp.Column):
            if not column.name:
                return None
            ref = (column.db or "", column.table or "", column.name)
            found[ref] = ref
    if not parsed:
        return None
    return tuple(found.values())
