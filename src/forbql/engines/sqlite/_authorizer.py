"""SQLite has no roles, so every read and call is checked at prepare time."""

from __future__ import annotations

from collections.abc import Callable
from sqlite3 import (
    SQLITE_DENY,
    SQLITE_FUNCTION,
    SQLITE_OK,
    SQLITE_READ,
    SQLITE_RECURSIVE,
    SQLITE_SELECT,
)
from typing import TYPE_CHECKING

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


def authorizer(restriction: Restriction, stored: frozenset[str]) -> Authorizer:
    """Build an authorizer that allows only the profile's reads and calls.

    Args:
        restriction: Restriction - What the profile may touch.
        stored: frozenset[str] - Names of every table and view in the file.

    Returns:
        Authorizer - The callback for `sqlite3.Connection.set_authorizer`.

    """
    cols = {table: frozenset(names) for table, names in restriction.tables.items()}
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
            allowed = _may_read(cols, stored, first or "", second or "", db)
        elif action == SQLITE_FUNCTION:
            allowed = (second or "").lower() in funcs
        elif action == SQLITE_RECURSIVE:
            allowed = restriction.allow_recursive
        return SQLITE_OK if allowed else SQLITE_DENY

    return _check


def _may_read(
    columns: dict[str, frozenset[str]],
    stored: frozenset[str],
    table: str,
    column: str,
    database: str | None,
) -> bool:
    """Tell whether the profile may read a table, or one column of it.

    SQLite leaves the database out for reads of a CTE and for whole-table reads
    (count(*)) of a table named without its schema. A name that is not a stored
    table is a CTE, whose own reads were authorized one by one.

    Returns:
        bool - True when the read is allowed.

    """
    if database is None and table not in stored:
        return True
    visible = columns.get(f"{database or 'main'}.{table}")
    return visible is not None and (not column or column in visible)
