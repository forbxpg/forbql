"""The service store for one workspace: its connections, their sealed DSNs."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, cast

from sqlalchemy import and_, delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as upsert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine

from forbql.policy import Engine

from ._errors import StoreError
from ._migrate import check_revision
from ._secrets import Sealed
from ._tables import DEFAULT_WORKSPACE, connection_secrets, connections, workspaces
from ._url import sqlalchemy_url

_ALL_PROFILES = ""
"""The `profile` of the connection's own DSN, which every profile without one uses."""

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncEngine

    from ._secrets import SecretKey


@dataclass(frozen=True, slots=True)
class StoredConnection:
    """A connection as the store lists it; its DSN never leaves sealed.

    Attributes:
        name: str - Connection name, as in the policy.
        engine: Engine - Which database it is.
        profiles: tuple[str, ...] - Profiles with a DSN of their own.

    """

    name: str
    engine: Engine
    profiles: tuple[str, ...]


class Store:
    """forbql's state for one workspace. Build it with `Store.open`.

    Args:
        engine: AsyncEngine - SQLAlchemy's engine over the store.
        workspace_id: UUID - The workspace.
        key: SecretKey | None - Seals and opens DSNs; reading anything else needs none.

    """

    engine: AsyncEngine
    workspace_id: UUID
    _key: SecretKey | None

    def __init__(
        self,
        engine: AsyncEngine,
        workspace_id: UUID,
        key: SecretKey | None,
    ) -> None:
        self.engine = engine
        self.workspace_id = workspace_id
        self._key = key

    @classmethod
    @asynccontextmanager
    async def open(
        cls,
        dsn: str,
        *,
        key: SecretKey | None = None,
        workspace: str = DEFAULT_WORKSPACE,
    ) -> AsyncGenerator[Self]:
        """Connect as the runtime role, and refuse a store at another revision.

        Args:
            dsn: str - The store as `forbql_app`.
            key: SecretKey | None - The master key, for DSNs.
            workspace: str - Workspace name.

        Yields:
            Self - The store; its connections close when the block ends.

        Raises:
            StoreError: If the store is unreachable, at another revision, or has no
                such workspace.

        """
        engine = create_async_engine(sqlalchemy_url(dsn), pool_pre_ping=True)
        try:
            try:
                async with engine.connect() as connection:
                    await check_revision(connection)
                    query = select(workspaces.c.id).where(
                        workspaces.c.name == workspace,
                    )
                    found = cast("UUID | None", await connection.scalar(query))
            except (SQLAlchemyError, OSError) as error:
                msg = f"cannot reach the store: {error}"
                raise StoreError(msg) from error
            if found is None:
                msg = f"the store has no workspace '{workspace}'"
                raise StoreError(msg)
            yield cls(engine, found, key)
        finally:
            await engine.dispose()

    async def add_connection(
        self,
        name: str,
        engine: Engine,
        dsn: str,
        *,
        profile: str | None = None,
    ) -> None:
        """Keep a connection's DSN sealed, or a profile's own DSN for it.

        Adding it again replaces the DSN.

        Args:
            name: str - Connection name, as in the policy.
            engine: Engine - Which database it is.
            dsn: str - The DSN.
            profile: str | None - A profile that connects with a role of its own.

        Raises:
            StoreError: If there is no key, or the connection has another engine.

        """
        sealed = self._need_key().seal(dsn, context=self._context(name, profile))
        async with self.engine.begin() as connection:
            query = select(connections.c.id, connections.c.engine).where(
                connections.c.workspace_id == self.workspace_id,
                connections.c.name == name,
            )
            row = cast(
                "tuple[UUID, str] | None",
                (await connection.execute(query)).one_or_none(),
            )
            if row is None:
                statement = (
                    insert(connections)
                    .values(workspace_id=self.workspace_id, name=name, engine=engine)
                    .returning(connections.c.id)
                )
                connection_id = cast("UUID", await connection.scalar(statement))
            elif row[1] != engine:
                msg = f"connection '{name}' is {row[1]}, not {engine}"
                raise StoreError(msg)
            else:
                connection_id = row[0]
            statement = upsert(connection_secrets).values(
                connection_id=connection_id,
                profile=profile or _ALL_PROFILES,
                key_id=sealed.key_id,
                sealed=sealed.blob,
            )
            _ = await connection.execute(
                statement.on_conflict_do_update(
                    index_elements=["connection_id", "profile"],
                    set_={"key_id": sealed.key_id, "sealed": sealed.blob},
                ),
            )

    async def connections(self) -> list[StoredConnection]:
        """List the workspace's connections, without their DSNs.

        Returns:
            list[StoredConnection] - By name.

        """
        own = func.array_agg(connection_secrets.c.profile).filter(
            connection_secrets.c.profile != _ALL_PROFILES,
        )
        query = (
            select(connections.c.name, connections.c.engine, own)
            .outerjoin(connection_secrets)
            .where(connections.c.workspace_id == self.workspace_id)
            .group_by(connections.c.name, connections.c.engine)
            .order_by(connections.c.name)
        )
        async with self.engine.connect() as connection:
            rows = cast(
                "list[tuple[str, str, list[str] | None]]",
                (await connection.execute(query)).all(),
            )
        return [
            StoredConnection(
                name=name,
                engine=Engine(engine),
                profiles=tuple(sorted(profiles or ())),
            )
            for name, engine, profiles in rows
        ]

    async def remove_connection(self, name: str, *, profile: str | None = None) -> bool:
        """Forget a connection, or only a profile's own DSN for it.

        Args:
            name: str - Connection name.
            profile: str | None - The profile whose own DSN goes.

        Returns:
            bool - Whether there was anything to remove.

        """
        mine = and_(
            connections.c.workspace_id == self.workspace_id,
            connections.c.name == name,
        )
        if profile is None:
            statement = delete(connections).where(mine)
        else:
            owner = select(connections.c.id).where(mine).scalar_subquery()
            statement = delete(connection_secrets).where(
                connection_secrets.c.connection_id == owner,
                connection_secrets.c.profile == profile,
            )
        async with self.engine.begin() as connection:
            result = await connection.execute(statement)
        return result.rowcount > 0

    async def dsn(self, connection: str, profile: str) -> tuple[Engine, str]:
        """Open the DSN a profile connects with: its own, else the connection's.

        Args:
            connection: str - Connection name.
            profile: str - Profile name.

        Returns:
            tuple[Engine, str] - The connection's engine and the DSN.

        Raises:
            StoreError: If there is no key, no such connection, or no DSN for the
                profile.

        """
        key = self._need_key()
        query = (
            select(
                connections.c.engine,
                connection_secrets.c.profile,
                connection_secrets.c.key_id,
                connection_secrets.c.sealed,
            )
            .join(connection_secrets)
            .where(
                connections.c.workspace_id == self.workspace_id,
                connections.c.name == connection,
                connection_secrets.c.profile.in_([profile, _ALL_PROFILES]),
            )
            .order_by(connection_secrets.c.profile.desc())
        )
        async with self.engine.connect() as db:
            row = cast(
                "tuple[str, str, str, bytes] | None",
                (await db.execute(query)).first(),
            )
        if row is None:
            msg = (
                f"the store has no DSN for connection '{connection}', profile "
                f"'{profile}': add it with `forbql connection add`"
            )
            raise StoreError(msg)
        engine, owner, key_id, blob = row
        sealed = Sealed(key_id=key_id, blob=blob)
        context = self._context(connection, owner or None)
        return Engine(engine), key.open(sealed, context=context)

    def _need_key(self) -> SecretKey:
        """Return the master key, or refuse: DSNs are never kept or read unsealed.

        Returns:
            SecretKey - The key.

        Raises:
            StoreError: If the store was opened without one.

        """
        if self._key is None:
            msg = (
                "set FORBQL_SECRET_KEY or FORBQL_SECRET_KEY_FILE: the store seals DSNs"
            )
            raise StoreError(msg)
        return self._key

    def _context(self, connection: str, profile: str | None) -> str:
        """Name where a DSN lives, so a sealed DSN moved elsewhere will not open.

        Args:
            connection: str - Connection name.
            profile: str | None - Profile with its own DSN, if any.

        Returns:
            str - `<workspace id>/<connection>/<profile>`.

        """
        return f"{self.workspace_id}/{connection}/{profile or _ALL_PROFILES}"
