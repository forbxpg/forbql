"""Schema snapshots in the store: each sync adds a version, none is ever changed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError

from forbql.firewall import SchemaCatalog

from ._errors import StoreError
from ._tables import schema_snapshots

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass(frozen=True, slots=True)
class StoredSnapshot:
    """One version of a connection's schema.

    Attributes:
        connection: str - Connection name.
        version: int - 1 for the first sync, then one more per sync.
        taken_at: datetime - When it was taken.
        catalog: SchemaCatalog - The schema.

    """

    connection: str
    version: int
    taken_at: datetime
    catalog: SchemaCatalog


class StoreSnapshots:
    """A workspace's schema snapshots.

    Args:
        engine: AsyncEngine - The store.
        workspace_id: UUID - Whose snapshots.

    """

    _engine: AsyncEngine
    _workspace_id: UUID

    def __init__(self, engine: AsyncEngine, workspace_id: UUID) -> None:
        self._engine = engine
        self._workspace_id = workspace_id

    async def add(self, connection: str, catalog: SchemaCatalog) -> StoredSnapshot:
        """Keep a new version of a connection's schema.

        Args:
            connection: str - Connection name.
            catalog: SchemaCatalog - The schema as read now.

        Returns:
            StoredSnapshot - The version kept.

        Raises:
            StoreError: If another sync added a version at the same moment.

        """
        mine = (
            schema_snapshots.c.workspace_id == self._workspace_id,
            schema_snapshots.c.connection == connection,
        )
        latest = select(func.coalesce(func.max(schema_snapshots.c.version), 0)).where(
            *mine,
        )
        statement = (
            insert(schema_snapshots)
            .values(
                workspace_id=self._workspace_id,
                connection=connection,
                version=latest.scalar_subquery() + 1,
                content_hash=catalog.content_hash(),
                catalog=catalog.model_dump(mode="json"),
            )
            .returning(schema_snapshots.c.version, schema_snapshots.c.taken_at)
        )
        try:
            async with self._engine.begin() as db:
                version, taken_at = cast(
                    "tuple[int, datetime]",
                    (await db.execute(statement)).one(),
                )
        except IntegrityError as error:
            msg = f"another sync of {connection} ran at the same moment; sync again"
            raise StoreError(msg) from error
        return StoredSnapshot(connection, version, taken_at, catalog)

    async def latest(self, connection: str) -> StoredSnapshot | None:
        """Read the newest version of a connection's schema.

        Args:
            connection: str - Connection name.

        Returns:
            StoredSnapshot | None - The newest version; None before the first sync.

        """
        query = (
            select(
                schema_snapshots.c.version,
                schema_snapshots.c.taken_at,
                schema_snapshots.c.catalog,
            )
            .where(
                schema_snapshots.c.workspace_id == self._workspace_id,
                schema_snapshots.c.connection == connection,
            )
            .order_by(schema_snapshots.c.version.desc())
            .limit(1)
        )
        async with self._engine.connect() as db:
            row = cast(
                "tuple[int, datetime, dict[str, object]] | None",
                (await db.execute(query)).one_or_none(),
            )
        if row is None:
            return None
        version, taken_at, catalog = row
        return StoredSnapshot(
            connection,
            version,
            taken_at,
            SchemaCatalog.model_validate(catalog),
        )
