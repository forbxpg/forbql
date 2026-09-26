"""The store's schema: migrations ship in the package and run as the owner role."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from ._errors import StoreError
from ._url import sqlalchemy_url

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

_MIGRATIONS = Path(__file__).parent / "migrations"


def _config(dsn: str | None = None) -> Config:
    """Configure Alembic without an ini file.

    Args:
        dsn: str | None - The store as the owner role; only migrations need it.

    Returns:
        Config - The configuration.

    """
    config = Config()
    config.set_main_option("script_location", str(_MIGRATIONS))
    config.set_main_option("path_separator", "os")
    if dsn is not None:
        config.attributes["url"] = sqlalchemy_url(dsn)
    return config


def head() -> str:
    """Return the revision this version of forbql needs.

    Returns:
        str - The newest migration's revision.

    Raises:
        StoreError: If the package ships no migrations.

    """
    revision = ScriptDirectory.from_config(_config()).get_current_head()
    if revision is None:
        msg = "the package ships no migrations"
        raise StoreError(msg)
    return revision


def migrate(owner_dsn: str) -> str:
    """Bring the store's schema up to this version of forbql.

    Args:
        owner_dsn: str - The store as the role that owns the `forbql` schema.

    Returns:
        str - The revision the store is at now.

    """
    command.upgrade(_config(owner_dsn), "head")
    return head()


async def check_revision(connection: AsyncConnection) -> None:
    """Refuse a store whose schema is not the one this forbql was built for.

    Args:
        connection: AsyncConnection - A connection to the store.

    Raises:
        StoreError: If the schema is missing or at another revision.

    """
    # The catalog, not the schema: before the first migration the runtime role may not
    # even look inside `forbql`.
    exists = text("""
        SELECT count(*) FROM pg_catalog.pg_tables
        WHERE schemaname = 'forbql' AND tablename = 'alembic_version'
    """)
    found = None
    if cast("int", await connection.scalar(exists)):
        query = text("SELECT version_num FROM forbql.alembic_version")
        found = cast("str | None", await connection.scalar(query))
    if found != head():
        msg = (
            f"the store's schema is at {found or 'nothing'}, this forbql needs "
            f"{head()}: run `forbql store migrate`"
        )
        raise StoreError(msg)
