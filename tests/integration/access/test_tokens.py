"""Issuing a token and presenting it: the store checks it on every call.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from forbql.access import (
    AccessDeniedError,
    Capability,
    Grant,
    IssuedToken,
    Principal,
    TokenParts,
    authenticate,
    issue_token,
)
from forbql.store import Store
from support.store import STORE_APP, STORE_SUPERUSER, fresh_store, store_sql

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("store")]

RUN = Grant.parse("bank:analyst:sql.run")
CHECK = Grant.parse("bank:analyst:sql.check")
DAY = timedelta(days=1)


@pytest.fixture
def store() -> str:
    return fresh_store()


def with_store[T](work: Callable[[Store], Awaitable[T]]) -> T:
    async def go() -> T:
        async with Store.open(STORE_APP) as store:
            return await work(store)

    return asyncio.run(go())


def issue(*grants: Grant, lifetime: timedelta = DAY) -> IssuedToken:
    return with_store(lambda store: issue_token(store, "ci", grants, lifetime=lifetime))


def present(value: str) -> Principal:
    return with_store(lambda store: authenticate(store, value))


def refusal(value: str) -> AccessDeniedError:
    with pytest.raises(AccessDeniedError) as caught:
        present(value)
    assert str(caught.value) == "the token is not valid"
    return caught.value


def test_a_token_opens_its_grants_and_no_more():
    token = issue(RUN, CHECK)

    principal = present(token.value)

    assert principal.name == f"token:{token.token_id}"
    assert principal.may(Capability.SQL_RUN, connection="bank", profile="analyst")
    assert principal.may(Capability.SQL_CHECK, connection="bank", profile="analyst")
    assert not principal.may(
        Capability.SCHEMA_READ,
        connection="bank",
        profile="analyst",
    )


def test_the_store_keeps_no_trace_of_the_secret():
    token = issue(RUN)
    parts = TokenParts.parse(token.value)
    assert parts is not None
    secret = parts.secret

    rows = store_sql(STORE_SUPERUSER, "SELECT * FROM forbql.tokens")

    assert token.value not in str(rows)
    assert secret not in str(rows)


def test_a_wrong_secret_is_refused():
    token = issue(RUN)
    forged = TokenParts(token_id=token.token_id, secret="A" * 43).value

    assert refusal(forged).reason == "wrong secret"


def test_an_unknown_token_is_refused():
    parts = TokenParts.parse(issue(RUN).value)
    assert parts is not None
    unknown = TokenParts(token_id="f" * 12, secret=parts.secret).value

    assert refusal(unknown).reason == "unknown token"


def test_something_else_is_refused():
    assert refusal("Bearer abc").reason == "not a forbql token"


def test_a_revoked_token_stops_at_once():
    token = issue(RUN)
    assert present(token.value)

    with_store(lambda store: store.tokens.revoke(token.token_id))

    assert refusal(token.value).reason == "revoked"


def test_an_expired_token_is_refused():
    token = issue(RUN)
    store_sql(
        STORE_SUPERUSER,
        """
        UPDATE forbql.tokens
        SET created_at = now() - interval '2 hours', expires_at = now() - interval '1 hour'
        """,
    )

    assert refusal(token.value).reason == "expired"


def test_grants_on_one_profile_merge():
    token = issue(RUN, CHECK)

    found = with_store(lambda store: store.tokens.find(token.token_id))

    assert found is not None
    assert [grant.capabilities for grant in found.grants] == [("sql.check", "sql.run")]


def test_a_token_without_grants_is_not_issued():
    with pytest.raises(ValueError, match="needs a grant"):
        issue()


@pytest.mark.parametrize("days", [0, 366])
def test_a_token_lives_at_most_a_year(days: int):
    with pytest.raises(ValueError, match="at most 365 days"):
        issue(RUN, lifetime=timedelta(days=days))
