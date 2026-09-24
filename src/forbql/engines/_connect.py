"""Opening an engine by kind, importing its driver only when it is used."""

from __future__ import annotations

from typing import TYPE_CHECKING, assert_never

from forbql.policy import Engine

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from forbql.engines import QueryEngine


async def connect(engine: Engine, dsn: str) -> QueryEngine:
    """Open a read-only connection.

    Args:
        engine: Engine - Which database it is.
        dsn: str - Connection string; for SQLite, a file path.

    Returns:
        QueryEngine - The open engine.

    Raises:
        ImportError: If the engine's extra is not installed.

    """
    try:
        opener = _engine_opener(engine)
    except ModuleNotFoundError as err:
        extra = engine.value
        msg = (
            f"forbql.engines.{extra} requires the '{extra}' extra: "
            f"pip install 'forbql[{extra}]'"
        )
        raise ImportError(msg) from err
    return await opener(dsn)


def _engine_opener(engine: Engine) -> Callable[[str], Awaitable[QueryEngine]]:
    """Open the connection the caller needs.

    Returns:
        `connect` function from the Engine

    """
    match engine:
        case Engine.SQLITE:
            from .sqlite import SQLiteEngine  # ruff: ignore[import-outside-top-level]

            return SQLiteEngine.connect

        case Engine.POSTGRES:
            from .postgres import PostgresEngine  # ruff: ignore[import-outside-top-level]

            return PostgresEngine.connect
        case Engine.MYSQL:
            from .mysql import MySQLEngine  # ruff: ignore[import-outside-top-level]

            return MySQLEngine.connect
        case _:
            assert_never(engine)
