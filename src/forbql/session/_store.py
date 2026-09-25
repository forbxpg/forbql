"""The service store behind a session: where DSNs and audit records come from."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forbql.store import Store, StoreError

from ._config import ForbqlSettings, SessionError, resolve_dsn, secret_key

if TYPE_CHECKING:
    from contextlib import AsyncExitStack

    from forbql.policy import Policy


async def open_store(stack: AsyncExitStack, settings: ForbqlSettings) -> Store | None:
    """Open the store `FORBQL_STORE_DSN` names, for as long as the stack lives.

    Args:
        stack: AsyncExitStack - Closes the store when the caller is done.
        settings: ForbqlSettings - Settings from the environment.

    Returns:
        Store | None - The store; None when none is configured, and DSNs and the
            audit log then come from the environment.

    Raises:
        SessionError: If the store is unreachable, at another revision, or the
            secret key is unusable.

    """
    if settings.store_dsn is None:
        return None
    dsn = settings.store_dsn.get_secret_value()
    try:
        return await stack.enter_async_context(
            Store.open(dsn, key=secret_key(settings)),
        )
    except StoreError as err:
        msg = f"the store refused: {err}"
        raise SessionError(msg) from err


async def find_dsn(  # ruff: ignore[too-many-arguments] - one parameter per source
    store: Store | None,
    settings: ForbqlSettings,
    *,
    policy: Policy,
    connection: str,
    profile: str,
    dsn: str | None,
) -> str:
    """Take the DSN given, else the store's for the profile, else the environment's.

    Args:
        store: Store | None - The store, if one is configured.
        settings: ForbqlSettings - Settings from the environment.
        policy: Policy - The policy; it names the engine the store must agree with.
        connection: str - Connection name.
        profile: str - Profile name.
        dsn: str | None - DSN passed by the caller.

    Returns:
        str - The DSN.

    Raises:
        SessionError: If none is found, or the store's engine is not the policy's.

    """
    if dsn:
        return dsn
    if store is None:
        return resolve_dsn(connection, None, settings)
    try:
        engine, found = await store.dsn(connection, profile)
    except StoreError as err:
        msg = f"the store refused: {err}"
        raise SessionError(msg) from err
    expected = policy.connection(connection).engine
    if engine is not expected:
        msg = f"the store keeps {connection} as {engine}; the policy says {expected}"
        raise SessionError(msg)
    return found
