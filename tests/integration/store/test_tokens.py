"""Tokens in the store: issued once, revoked for good, their secrets never kept.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import asyncpg
import pytest

from forbql.store import Store, StoredGrant, StoreError
from support.store import STORE_APP, fresh_store, store_sql

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("store")]

PUBLIC_ID = "1a2b3c4d5e6f"
GRANT = StoredGrant(
    connection="bank",
    profile="analyst",
    capabilities=("sql.check", "sql.run"),
)


@pytest.fixture
def store() -> str:
    return fresh_store()


def with_store[T](work: Callable[[Store], Awaitable[T]]) -> T:
    async def go() -> T:
        async with Store.open(STORE_APP) as store:
            return await work(store)

    return asyncio.run(go())


def issue(public_id: str = PUBLIC_ID, name: str = "ci") -> None:
    with_store(
        lambda store: store.tokens.add(
            token_id=public_id,
            name=name,
            secret_hash="h" * 64,
            expires_at=datetime.now(UTC) + timedelta(days=90),
            grants=[GRANT],
        ),
    )


def test_an_issued_token_is_found_with_its_grants():
    issue()

    found = with_store(lambda store: store.tokens.find(PUBLIC_ID))

    assert found is not None
    assert found.name == "ci"
    assert found.secret_hash == "h" * 64
    assert found.revoked_at is None
    assert found.grants == (GRANT,)


def test_an_unknown_id_finds_nothing():
    assert with_store(lambda store: store.tokens.find("ffffffffffff")) is None


def test_a_name_is_taken_once():
    issue()

    with pytest.raises(StoreError, match="already has a token named 'ci'"):
        issue(public_id="0f0f0f0f0f0f")


def test_the_list_holds_every_token():
    issue()
    issue(public_id="0f0f0f0f0f0f", name="agent")

    names = [token.name for token in with_store(lambda store: store.tokens.all())]

    assert sorted(names) == ["agent", "ci"]


def test_revoking_is_once_and_for_good():
    issue()

    assert with_store(lambda store: store.tokens.revoke(PUBLIC_ID))
    assert not with_store(lambda store: store.tokens.revoke(PUBLIC_ID))
    found = with_store(lambda store: store.tokens.find(PUBLIC_ID))
    assert found is not None
    assert found.revoked_at is not None


def test_the_store_refuses_to_unrevoke():
    issue()
    with_store(lambda store: store.tokens.revoke(PUBLIC_ID))

    with pytest.raises(asyncpg.RaiseError, match="stays revoked"):
        store_sql(STORE_APP, "UPDATE forbql.tokens SET revoked_at = NULL")


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE forbql.tokens SET secret_hash = 'x'",
        "UPDATE forbql.tokens SET expires_at = expires_at + interval '1 year'",
        "DELETE FROM forbql.tokens",
        "UPDATE forbql.token_grants SET capabilities = ARRAY['sql.run']",
        "DELETE FROM forbql.token_grants",
    ],
)
def test_the_runtime_role_changes_nothing_but_revocation(sql: str):
    issue()

    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        store_sql(STORE_APP, sql)


@pytest.mark.parametrize(
    "capabilities",
    ["ARRAY['sql.drop']", "ARRAY[]::text[]"],
)
def test_the_store_accepts_only_known_capabilities(capabilities: str):
    issue()

    with pytest.raises(asyncpg.CheckViolationError):
        store_sql(
            STORE_APP,
            f"""
            INSERT INTO forbql.token_grants (token_id, connection, profile, capabilities)
            VALUES ('{PUBLIC_ID}', 'shop', 'analyst', {capabilities})
            """,
        )
