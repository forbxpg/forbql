"""The demo bank on the local stand, reached without forbql: the database as the only line."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import psycopg
import pymysql

from forbql import Engine

if TYPE_CHECKING:
    from pathlib import Path

# Ports and passwords of deploy/compose.yaml.
PG_READER = "host=127.0.0.1 port=55433 dbname=bank user=forbql_reader password=forbql_reader connect_timeout=5"
PG_ADMIN = "host=127.0.0.1 port=55433 dbname=bank user=postgres password=demo-local-only connect_timeout=5"
MYSQL_READER = ("forbql_reader", "forbql_reader")
MYSQL_ADMIN = ("root", "demo-local-only")
# What forbql's engines will set for every request; until then the harness sets it.
TIMEOUT_SECONDS = 2


@dataclass
class Outcome:
    error: str | None = None
    rows: list[tuple[object, ...]] = field(default_factory=list)
    seconds: float = 0.0

    def cells(self) -> list[str]:
        return [str(cell) for row in self.rows for cell in row]


def _mysql(account: tuple[str, str]) -> pymysql.Connection[pymysql.cursors.Cursor]:
    user, password = account
    return pymysql.connect(
        host="127.0.0.1",
        port=53306,
        database="bank",
        user=user,
        password=password,
        autocommit=True,
        read_timeout=30,
    )


def run_as_reader(engine: Engine, sql: str, sqlite_file: Path) -> Outcome:
    """Run SQL as the demo reader, straight into the database, with a timeout.

    Returns:
        Outcome - The error or the rows, and how long it took.

    """
    outcome = Outcome()
    start = time.monotonic()
    try:
        outcome.rows = _execute(engine, sql, sqlite_file)
    except (psycopg.Error, pymysql.Error, sqlite3.Error) as error:
        outcome.error = f"{type(error).__name__}: {error}"
    outcome.seconds = time.monotonic() - start
    return outcome


def _execute(engine: Engine, sql: str, sqlite_file: Path) -> list[tuple[object, ...]]:
    if engine is Engine.POSTGRES:
        with psycopg.connect(PG_READER, autocommit=True) as connection:
            timeout = f"SET statement_timeout = {TIMEOUT_SECONDS * 1000}"
            connection.execute(timeout.encode())
            # Bytes: the harness sends the attack text as is, like a naive client would.
            cursor = connection.execute(sql.encode())
            return list(cursor.fetchall()) if cursor.description else []
    if engine is Engine.MYSQL:
        with _mysql(MYSQL_READER) as connection, connection.cursor() as cursor:
            cursor.execute(f"SET SESSION max_execution_time = {TIMEOUT_SECONDS * 1000}")
            cursor.execute(sql)
            return list(cursor.fetchall())
    connection = sqlite3.connect(f"file:{sqlite_file}?mode=ro", uri=True)
    deadline = time.monotonic() + TIMEOUT_SECONDS
    connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
    try:
        return list(connection.execute(sql).fetchall())
    finally:
        connection.close()


def as_admin(engine: Engine, sql: str, sqlite_file: Path) -> list[tuple[object, ...]]:
    """Read as the database owner, to check what an attack left behind.

    Returns:
        list[tuple[object, ...]] - The rows.

    """
    if engine is Engine.POSTGRES:
        with psycopg.connect(PG_ADMIN, autocommit=True) as connection:
            return list(connection.execute(sql.encode()).fetchall())
    if engine is Engine.MYSQL:
        with _mysql(MYSQL_ADMIN) as connection, connection.cursor() as cursor:
            cursor.execute(sql)
            return list(cursor.fetchall())
    connection = sqlite3.connect(f"file:{sqlite_file}?mode=ro", uri=True)
    try:
        return list(connection.execute(sql).fetchall())
    finally:
        connection.close()


def build_sqlite(path: Path, seed: Path) -> Path:
    connection = sqlite3.connect(path)
    connection.executescript(seed.read_text(encoding="utf-8"))
    connection.close()
    return path
