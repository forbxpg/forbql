"""The local stand of deploy/compose.yaml: DSNs, and the demo data it was seeded with."""

from __future__ import annotations

import asyncio
import runpy
from contextlib import contextmanager
from functools import cache
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import asyncpg
import pymysql

from forbql import Engine

from .corpus import DEMO

if TYPE_CHECKING:
    from collections.abc import Generator, Sequence

# Ports and passwords of deploy/compose.yaml.
READER = {
    Engine.POSTGRES: "postgresql://forbql_reader:forbql_reader@127.0.0.1:55433/bank",
    Engine.MYSQL: "mysql://forbql_reader:forbql_reader@127.0.0.1:53306/bank",
}
ADMIN = {
    Engine.POSTGRES: "postgresql://postgres:demo-local-only@127.0.0.1:55433/bank",
    Engine.MYSQL: "mysql://root:demo-local-only@127.0.0.1:53306/bank",
}
PROBE = {
    Engine.POSTGRES: "postgresql://forbql_probe:forbql_probe@127.0.0.1:55433/bank",
    Engine.MYSQL: "mysql://forbql_probe:forbql_probe@127.0.0.1:53306/bank",
}
_CREATE_PROBE = {
    Engine.POSTGRES: (
        "CREATE ROLE forbql_probe LOGIN PASSWORD 'forbql_probe'",
        "GRANT CONNECT ON DATABASE bank TO forbql_probe",
        "GRANT USAGE ON SCHEMA public TO forbql_probe",
    ),
    Engine.MYSQL: ("CREATE USER 'forbql_probe'@'%' IDENTIFIED BY 'forbql_probe'",),
}
_DROP_PROBE = {
    Engine.POSTGRES: (
        """DO $$ BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'forbql_probe') THEN
                DROP OWNED BY forbql_probe;
                DROP ROLE forbql_probe;
            END IF;
        END $$""",
    ),
    Engine.MYSQL: ("DROP USER IF EXISTS 'forbql_probe'@'%'",),
}


@cache
def seeded_names() -> tuple[tuple[object, ...], ...]:
    """Every client's id and full name, as the seed generator wrote them.

    Returns:
        tuple[tuple[object, ...], ...] - `(id, full_name)` in id order.

    """
    tables = runpy.run_path(str(DEMO / "generate.py"))["build"]()
    clients = next(table for table in tables if table.name == "clients")
    return tuple((row[0], row[1]) for row in clients.rows)


@contextmanager
def probe_account(
    engine: Engine,
    grants: Sequence[str] = (),
    cleanup: Sequence[str] = (),
) -> Generator[str]:
    """A throwaway account holding exactly `grants`, dropped afterwards.

    `cleanup` removes whatever `grants` created besides privileges; it runs before
    the account is made too, so a run that crashed leaves nothing behind.

    Yields:
        str - The account's DSN.

    """
    as_owner(engine, [*cleanup, *_DROP_PROBE[engine], *_CREATE_PROBE[engine], *grants])
    try:
        yield PROBE[engine]
    finally:
        as_owner(engine, [*cleanup, *_DROP_PROBE[engine]])


def as_owner(engine: Engine, statements: Sequence[str]) -> None:
    """Run statements on the stand as the database owner, outside forbql."""
    if engine is Engine.POSTGRES:

        async def go() -> None:
            connection = await asyncpg.connect(ADMIN[engine])
            try:
                for statement in statements:
                    _ = await connection.execute(statement)
            finally:
                await connection.close()

        asyncio.run(go())
        return
    url = urlsplit(ADMIN[engine])
    connection = pymysql.connect(
        host=url.hostname,
        port=url.port or 3306,
        user=url.username or "",
        password=url.password or "",
        database=url.path.lstrip("/"),
        autocommit=True,
    )
    with connection, connection.cursor() as cursor:
        for statement in statements:
            _ = cursor.execute(statement)
