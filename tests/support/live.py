"""The demo bank on the local stand, reached through forbql's engines with the firewall off."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from forbql import Engine
from forbql.engines import QueryError, Restriction, connect
from forbql.policy import Limits

from .corpus import PROFILE, connection_name, demo_firewall
from .stand import ADMIN, READER

if TYPE_CHECKING:
    from pathlib import Path

TIMEOUT_SECONDS = 2
LIMITS = Limits(statement_timeout_ms=TIMEOUT_SECONDS * 1000)


@dataclass
class Outcome:
    error: str | None = None
    rows: list[tuple[object, ...]] = field(default_factory=list)
    seconds: float = 0.0

    def cells(self) -> list[str]:
        return [str(cell) for row in self.rows for cell in row]


async def _run(engine: Engine, dsn: str, sql: str, *, restrict: bool) -> Outcome:
    outcome = Outcome()
    opened = await connect(engine, dsn)
    try:
        _ = await opened.snapshot()
        if restrict:
            await opened.restrict(
                Restriction(
                    tables=demo_firewall().visible(connection_name(engine), PROFILE),
                    functions=frozenset(),
                    allow_recursive=False,
                ),
            )
        start = time.monotonic()
        try:
            outcome.rows = list((await opened.execute(sql, LIMITS)).rows)
        except QueryError as error:
            outcome.error = f"{error.error_class}: {error.detail}"
        outcome.seconds = time.monotonic() - start
    finally:
        await opened.close()
    return outcome


def run_as_reader(engine: Engine, sql: str, sqlite_file: Path) -> Outcome:
    """Run SQL through the engine as the demo reader, with the firewall off.

    SQLite has no reader role; the engine's authorizer, restricted to the demo
    profile, takes its place.

    Returns:
        Outcome - The error or the rows, and how long the query took.

    """
    dsn = str(sqlite_file) if engine is Engine.SQLITE else READER[engine]
    return asyncio.run(_run(engine, dsn, sql, restrict=True))


def run_as_admin(engine: Engine, sql: str, sqlite_file: Path) -> Outcome:
    """Run SQL through the engine as the database owner, with the firewall off.

    Only the engine's read-only transaction stands between the owner and a write.

    Returns:
        Outcome - The error or the rows, and how long the query took.

    """
    dsn = str(sqlite_file) if engine is Engine.SQLITE else ADMIN[engine]
    return asyncio.run(_run(engine, dsn, sql, restrict=False))


def as_admin(engine: Engine, sql: str, sqlite_file: Path) -> list[tuple[object, ...]]:
    """Read as the database owner, to check what an attack left behind.

    Returns:
        list[tuple[object, ...]] - The rows.

    """
    outcome = run_as_admin(engine, sql, sqlite_file)
    assert outcome.error is None, outcome.error
    return outcome.rows


def build_sqlite(path: Path, seed: Path) -> Path:
    connection = sqlite3.connect(path)
    connection.executescript(seed.read_text(encoding="utf-8"))
    connection.close()
    return path
