"""The service store of deploy/compose.yaml: the live suite's own database, forbql_test."""

from __future__ import annotations

import asyncio

import asyncpg

# Roles and passwords of deploy/store/10-roles.sql.
STORE_SUPERUSER = "postgresql://postgres:store-local-only@127.0.0.1:55432/forbql_test"
STORE_OWNER = "postgresql://forbql_owner:owner-local-only@127.0.0.1:55432/forbql_test"
STORE_APP = "postgresql://forbql_app:app-local-only@127.0.0.1:55432/forbql_test"


def store_sql(dsn: str, *statements: str) -> list[list[tuple[object, ...]]]:
    """Run statements on the store outside forbql; return the rows of each.

    Returns:
        list[list[tuple[object, ...]]] - Rows per statement.

    """

    async def go() -> list[list[tuple[object, ...]]]:
        connection = await asyncpg.connect(dsn)
        try:
            return [
                [tuple(record.values()) for record in await connection.fetch(sql)]
                for sql in statements
            ]
        finally:
            await connection.close()

    return asyncio.run(go())


def empty_store() -> None:
    """Drop everything in the store's schema, as a fresh install has it."""
    _ = store_sql(
        STORE_SUPERUSER,
        "DROP SCHEMA IF EXISTS forbql CASCADE",
        "CREATE SCHEMA forbql AUTHORIZATION forbql_owner",
    )
