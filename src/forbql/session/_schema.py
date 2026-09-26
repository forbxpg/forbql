"""Syncing a connection's schema into the store, and comparing it with the last sync."""

from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import TYPE_CHECKING

from forbql.engines import QueryError
from forbql.firewall import SchemaCatalog
from forbql.knowledge import diff_catalogs
from forbql.policy import Policy, load_policy
from forbql.store import StoreError

from ._config import ForbqlSettings, SessionError
from ._session import open_engine
from ._store import find_dsn, open_store

if TYPE_CHECKING:
    from pathlib import Path

    from forbql.store import Store


@dataclass(frozen=True, slots=True)
class SchemaSync:
    """What a sync did.

    Attributes:
        version: int - The version the store holds now.
        changes: tuple[str, ...] - Changes since the version before; every table for
            the first sync; none when nothing changed and no version was added.

    """

    version: int
    changes: tuple[str, ...]


async def sync_schema(
    policy: Policy | str | Path,
    *,
    connection: str,
    dsn: str | None = None,
) -> SchemaSync:
    """Read a connection's schema and keep it as the reviewed one, if it changed.

    Args:
        policy: Policy | str | Path - The policy, or the path to its file.
        connection: str - Connection name.
        dsn: str | None - DSN; defaults to the connection's own in the store.

    Returns:
        SchemaSync - The version kept and what changed.

    Raises:
        SessionError: If there is no store, or it or the database refuses.

    """
    async with AsyncExitStack() as stack:
        store, live = await _read_live(stack, policy, connection, dsn)
        previous = await store.snapshots.latest(connection)
        before = previous.catalog if previous else _empty(live)
        changes = diff_catalogs(before, live)
        if previous is not None and not changes:
            return SchemaSync(version=previous.version, changes=())
        try:
            kept = await store.snapshots.add(connection, live)
        except StoreError as err:
            msg = f"the store refused: {err}"
            raise SessionError(msg) from err
    return SchemaSync(version=kept.version, changes=tuple(changes))


async def schema_changes(
    policy: Policy | str | Path,
    *,
    connection: str,
    dsn: str | None = None,
) -> list[str]:
    """Compare a connection's schema now with the version synced last.

    Args:
        policy: Policy | str | Path - The policy, or the path to its file.
        connection: str - Connection name.
        dsn: str | None - DSN; defaults to the connection's own in the store.

    Returns:
        list[str] - The changes; empty when there are none.

    Raises:
        SessionError: If there is no store, no synced version, or a refusal.

    """
    async with AsyncExitStack() as stack:
        store, live = await _read_live(stack, policy, connection, dsn)
        previous = await store.snapshots.latest(connection)
    if previous is None:
        msg = f"no synced schema of {connection}: run `forbql schema sync {connection}`"
        raise SessionError(msg)
    return diff_catalogs(previous.catalog, live)


async def _read_live(
    stack: AsyncExitStack,
    policy: Policy | str | Path,
    connection: str,
    dsn: str | None,
) -> tuple[Store, SchemaCatalog]:
    """Open the store and read the connection's schema as its own DSN's role sees it.

    Args:
        stack: AsyncExitStack - Closes what is opened.
        policy: Policy | str | Path - The policy.
        connection: str - Connection name.
        dsn: str | None - DSN given by the caller.

    Returns:
        tuple[Store, SchemaCatalog] - The store and the schema now.

    Raises:
        SessionError: If there is no store, or it or the database refuses.

    """
    settings = ForbqlSettings()
    loaded = policy if isinstance(policy, Policy) else load_policy(policy)
    _ = loaded.connection(connection)
    store = await open_store(stack, settings)
    if store is None:
        msg = "schema snapshots live in the store: set FORBQL_STORE_DSN"
        raise SessionError(msg)
    found = await find_dsn(
        store,
        settings,
        policy=loaded,
        connection=connection,
        profile="",
        dsn=dsn,
    )
    engine = await open_engine(loaded, connection, found)
    _ = stack.push_async_callback(engine.close)
    try:
        return store, await engine.describe()
    except QueryError as err:
        msg = f"failed to read the schema of {connection}: {err.hint}"
        raise SessionError(msg) from err


def _empty(like: SchemaCatalog) -> SchemaCatalog:
    """Make the catalog a first sync is compared with.

    Args:
        like: SchemaCatalog - The schema read now.

    Returns:
        SchemaCatalog - No tables, the same default schema.

    """
    return SchemaCatalog(default_schema=like.default_schema, tables={})
