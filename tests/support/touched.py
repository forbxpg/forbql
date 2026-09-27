"""The tables a database reads for a query, as its own planner reports them."""

from __future__ import annotations

import json
import re
import sqlite3
from typing import TYPE_CHECKING, LiteralString, cast
from urllib.parse import urlsplit

import psycopg
import pymysql

from forbql import Engine

from .stand import ADMIN

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_TRACED = re.compile(r"`([^`]*)`(?:\.`([^`]*)`)?")
_SQLITE_READ = 20
_SQLITE_OK = 0


def touched(engine: Engine, sql: str, sqlite_file: Path) -> set[str] | None:
    """Ask the database which tables a query reads, without running it.

    As the owner, so that no missing privilege hides a read.

    Returns:
        set[str] | None - `schema.table` names, lower case; None when the database
            refuses the query, which reads nothing then.

    """
    try:
        if engine is Engine.POSTGRES:
            return _postgres(sql)
        if engine is Engine.MYSQL:
            return _mysql(sql)
        return _sqlite(sql, sqlite_file)
    except (psycopg.Error, pymysql.Error, sqlite3.Error):
        return None


def _postgres(sql: str) -> set[str]:
    query = cast("LiteralString", f"EXPLAIN (VERBOSE, FORMAT JSON) {sql}")
    with psycopg.connect(ADMIN[Engine.POSTGRES]) as connection:
        row = cast("tuple[object]", connection.execute(query).fetchone())
    found: set[str] = set()

    def add(node: dict[str, object]) -> None:
        found.add(f"{node['Schema']}.{node['Relation Name']}".lower())

    _walk(row[0], "Relation Name", add)
    return found


def _mysql(sql: str) -> set[str]:
    url = urlsplit(ADMIN[Engine.MYSQL])
    database = url.path.lstrip("/")
    connection = pymysql.connect(
        host=url.hostname,
        port=url.port or 3306,
        user=url.username or "",
        password=url.password or "",
        database=database,
    )
    # EXPLAIN names tables by their aliases; the optimizer trace writes them in full.
    with connection, connection.cursor() as cursor:
        _ = cursor.execute("SET optimizer_trace = 'enabled=on'")
        _ = cursor.execute(f"EXPLAIN {sql}")
        _ = cursor.fetchall()
        _ = cursor.execute("SELECT trace FROM information_schema.optimizer_trace")
        row = cast("tuple[str]", cursor.fetchone())
        # The trace names a CTE like a table; only stored tables and views count.
        _ = cursor.execute(
            "SELECT table_schema, table_name FROM information_schema.tables",
        )
        stored = {f"{schema}.{name}".lower() for schema, name in cursor.fetchall()}
    found: set[str] = set()

    def add(node: dict[str, object]) -> None:
        # "`clients` `c`" or "`other`.`t` `x`"; "`` `d`" and "`<subquery2>`" are the
        # query's own intermediate results.
        named = _TRACED.match(str(node["table"]))
        if named is None:
            return
        schema, table = (named[1], named[2]) if named[2] else (database, named[1])
        if table and not table.startswith("<"):
            found.add(f"{schema}.{table}".lower())

    _walk(json.loads(row[0]), "table", add)
    return found & stored


def _sqlite(sql: str, sqlite_file: Path) -> set[str]:
    found: set[str] = set()

    def record(
        action: int,
        table: str | None,
        _column: str | None,
        database: str | None,
        _trigger: str | None,
    ) -> int:
        if action == _SQLITE_READ and table and database:
            found.add(f"{database}.{table}".lower())
        return _SQLITE_OK

    connection = sqlite3.connect(sqlite_file)
    try:
        connection.set_authorizer(record)
        _ = connection.execute(f"EXPLAIN {sql}").fetchall()
    finally:
        connection.close()
    return found


def _walk(node: object, key: str, visit: Callable[[dict[str, object]], None]) -> None:
    if isinstance(node, dict):
        mapping = cast("dict[str, object]", node)
        if key in mapping:
            visit(mapping)
        for value in mapping.values():
            _walk(value, key, visit)
    elif isinstance(node, list):
        for item in cast("list[object]", node):
            _walk(item, key, visit)
