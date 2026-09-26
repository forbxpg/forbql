"""Tokens in the store: their ids, the hashes of their secrets, their grants."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError

from ._errors import StoreError
from ._tables import token_grants, tokens

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy import ColumnElement
    from sqlalchemy.ext.asyncio import AsyncEngine

    type _Row = Mapping[str, object]


@dataclass(frozen=True, slots=True)
class StoredGrant:
    """A token's grant as the store keeps it.

    Attributes:
        connection: str - Connection name.
        profile: str - Profile name.
        capabilities: tuple[str, ...] - Capability names.

    """

    connection: str
    profile: str
    capabilities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StoredToken:
    """A token as the store keeps it: never its secret.

    Attributes:
        token_id: str - The token's public id.
        name: str - What the operator called it.
        secret_hash: str - SHA-256 of the secret.
        created_at: datetime - When it was issued.
        expires_at: datetime - When it stops working.
        revoked_at: datetime | None - When it was revoked, if it was.
        grants: tuple[StoredGrant, ...] - What it may do.

    """

    token_id: str
    name: str
    secret_hash: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    grants: tuple[StoredGrant, ...]


class StoreTokens:
    """A workspace's tokens. The runtime role issues and revokes; nothing else changes.

    Args:
        engine: AsyncEngine - The store.
        workspace_id: UUID - Whose tokens.

    """

    _engine: AsyncEngine
    _workspace_id: UUID

    def __init__(self, engine: AsyncEngine, workspace_id: UUID) -> None:
        self._engine = engine
        self._workspace_id = workspace_id

    async def add(
        self,
        *,
        token_id: str,
        name: str,
        secret_hash: str,
        expires_at: datetime,
        grants: Sequence[StoredGrant],
    ) -> None:
        """Keep a new token and its grants, in one transaction.

        Args:
            token_id: str - Its public id.
            name: str - What the operator calls it; unique in the workspace.
            secret_hash: str - SHA-256 of its secret.
            expires_at: datetime - When it stops working.
            grants: Sequence[StoredGrant] - What it may do.

        Raises:
            StoreError: If the name is taken.

        """
        try:
            async with self._engine.begin() as connection:
                _ = await connection.execute(
                    insert(tokens).values(
                        id=token_id,
                        workspace_id=self._workspace_id,
                        name=name,
                        secret_hash=secret_hash,
                        expires_at=expires_at,
                    ),
                )
                _ = await connection.execute(
                    insert(token_grants),
                    [
                        {
                            "token_id": token_id,
                            "connection": grant.connection,
                            "profile": grant.profile,
                            "capabilities": list(grant.capabilities),
                        }
                        for grant in grants
                    ],
                )
        except IntegrityError as error:
            msg = f"the workspace already has a token named '{name}'"
            raise StoreError(msg) from error

    async def find(self, token_id: str) -> StoredToken | None:
        """Look a token up by its id.

        Args:
            token_id: str - The public id.

        Returns:
            StoredToken | None - The token; None if there is none.

        """
        found = await self._read(tokens.c.id == token_id)
        return found[0] if found else None

    async def all(self) -> list[StoredToken]:
        """List the workspace's tokens, newest first.

        Returns:
            list[StoredToken] - Revoked and expired ones too.

        """
        return await self._read()

    async def revoke(self, token_id: str) -> bool:
        """Revoke a token now; the store refuses to undo it.

        Args:
            token_id: str - The public id.

        Returns:
            bool - Whether a live token was revoked.

        """
        statement = (
            update(tokens)
            .where(
                tokens.c.workspace_id == self._workspace_id,
                tokens.c.id == token_id,
                tokens.c.revoked_at.is_(None),
            )
            .values(revoked_at=func.now())
        )
        async with self._engine.begin() as connection:
            result = await connection.execute(statement)
        return result.rowcount > 0

    async def _read(self, *conditions: ColumnElement[bool]) -> list[StoredToken]:
        """Read tokens with their grants.

        Args:
            *conditions: ColumnElement[bool] - Extra filters on `tokens`.

        Returns:
            list[StoredToken] - Newest first.

        """
        query = (
            select(tokens)
            .where(tokens.c.workspace_id == self._workspace_id, *conditions)
            .order_by(tokens.c.created_at.desc(), tokens.c.id)
        )
        async with self._engine.connect() as connection:
            rows = cast(
                "Sequence[_Row]",
                (await connection.execute(query)).mappings().all(),
            )
            ids = [str(row["id"]) for row in rows]
            grants_query = (
                select(token_grants)
                .where(token_grants.c.token_id.in_(ids))
                .order_by(token_grants.c.connection, token_grants.c.profile)
            )
            grant_rows = cast(
                "Sequence[_Row]",
                (await connection.execute(grants_query)).mappings().all(),
            )
        grants: dict[str, list[StoredGrant]] = {}
        for row in grant_rows:
            grants.setdefault(str(row["token_id"]), []).append(
                StoredGrant(
                    connection=str(row["connection"]),
                    profile=str(row["profile"]),
                    capabilities=tuple(cast("list[str]", row["capabilities"])),
                ),
            )
        return [
            StoredToken(
                token_id=str(row["id"]),
                name=str(row["name"]),
                secret_hash=str(row["secret_hash"]),
                created_at=cast("datetime", row["created_at"]),
                expires_at=cast("datetime", row["expires_at"]),
                revoked_at=cast("datetime | None", row["revoked_at"]),
                grants=tuple(grants.get(str(row["id"]), ())),
            )
            for row in rows
        ]
