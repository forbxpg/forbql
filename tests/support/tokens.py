"""Tokens on the stand's store, and the audit records they leave there."""

from __future__ import annotations

import asyncio

from forbql.access import Grant, IssuedToken, issue_token
from forbql.store import Store
from support.store import STORE_APP, store_sql


def issue(name: str, *grants: str) -> IssuedToken:
    """Issue a token with grants written `connection:profile:capabilities`.

    Returns:
        IssuedToken - The token.

    """

    async def go() -> IssuedToken:
        async with Store.open(STORE_APP) as store:
            return await issue_token(store, name, [Grant.parse(g) for g in grants])

    return asyncio.run(go())


def revoke(token_id: str) -> None:
    """Revoke a token now."""

    async def go() -> None:
        async with Store.open(STORE_APP) as store:
            _ = await store.tokens.revoke(token_id)

    asyncio.run(go())


def audited() -> list[tuple[object, ...]]:
    """Read the store's audit chain: principal, action, what was asked, the reason.

    Returns:
        list[tuple[object, ...]] - One row per record, oldest first.

    """
    [rows] = store_sql(
        STORE_APP,
        "SELECT principal, action, sql, error_class FROM forbql.audit_records ORDER BY seq",
    )
    return rows
