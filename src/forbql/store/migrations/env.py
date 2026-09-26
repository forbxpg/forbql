"""Alembic's entry point for the store; `forbql store migrate` calls it."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from forbql.store._tables import SCHEMA, metadata

if TYPE_CHECKING:
    from sqlalchemy import Connection


def _run(connection: Connection) -> None:
    """Apply the migrations over one connection, in one transaction.

    Args:
        connection: Connection - The owner's connection.

    """
    context.configure(
        connection=connection,
        target_metadata=metadata,
        version_table_schema=SCHEMA,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _main() -> None:
    """Connect as the owner and migrate."""
    url = str(context.config.attributes["url"])  # pyright: ignore[reportAny]
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run)
    finally:
        await engine.dispose()


asyncio.run(_main())
