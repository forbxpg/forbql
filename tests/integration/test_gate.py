"""Letting tokens in to one profile, and auditing the refusals, on the stand.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import pytest

import forbql
from forbql import Engine, SessionError
from forbql.access import Capability
from forbql.policy import load_policy
from forbql.session import Admission, Gate
from support.corpus import DEMO
from support.stand import READER
from support.store import fresh_store
from support.tokens import audited, issue, revoke

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

POLICY = load_policy(DEMO / "forbql.yaml")


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORBQL_STORE_DSN", fresh_store())


def admit(presented: str) -> Admission | None:
    async def go() -> Admission | None:
        async with Gate(POLICY, connection="bank-postgres", profile="analyst") as gate:
            return await gate.admit(presented)

    return asyncio.run(go())


@pytest.mark.usefixtures("store")
def test_a_granted_token_is_let_in_with_what_it_may_do_here():
    token = issue("agent", "bank-postgres:analyst:schema.read,sql.run")

    admitted = admit(token.value)

    assert admitted == Admission(
        principal=f"token:{token.token_id}",
        capabilities=frozenset({Capability.SCHEMA_READ, Capability.SQL_RUN}),
    )
    assert audited() == []


@pytest.mark.usefixtures("store")
def test_a_token_granted_elsewhere_is_let_in_with_nothing_and_audited():
    token = issue("elsewhere", "bank-mysql:analyst:sql.run")

    admitted = admit(token.value)

    assert admitted is not None
    assert admitted.capabilities == frozenset()
    assert audited() == [
        (f"token:{token.token_id}", "access.denied", "authenticate", "no grant"),
    ]


@pytest.mark.usefixtures("store")
@pytest.mark.parametrize("reason", ["revoked", "wrong secret"])
def test_a_known_token_that_fails_is_audited(reason: str):
    token = issue("agent", "bank-postgres:analyst:sql.run")
    presented = token.value
    if reason == "revoked":
        revoke(token.token_id)
    else:
        presented = presented[:-4] + (
            "AAAA" if not presented.endswith("AAAA") else "BBBB"
        )

    assert admit(presented) is None
    assert audited() == [
        (f"token:{token.token_id}", "access.denied", "authenticate", reason),
    ]


@pytest.mark.usefixtures("store")
@pytest.mark.parametrize("presented", ["garbage", "fql_000000000000_" + "A" * 43])
def test_what_the_store_does_not_know_is_only_logged(
    presented: str,
    caplog: pytest.LogCaptureFixture,
):
    with caplog.at_level(logging.WARNING, logger="forbql.session._gate"):
        assert admit(presented) is None

    assert audited() == []
    assert "refused a request" in caplog.text


def test_there_is_no_gate_without_a_store(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("FORBQL_STORE_DSN", raising=False)

    with pytest.raises(SessionError, match="tokens live in the store"):
        _ = admit("garbage")


def test_a_session_acting_for_a_token_records_that_token(tmp_path: Path):
    log = tmp_path / "audit.jsonl"

    async def go() -> None:
        async with forbql.connect(
            POLICY,
            connection="bank-postgres",
            profile="analyst",
            dsn=READER[Engine.POSTGRES],
            audit_log=log,
        ) as session:
            _ = await session.acting_as("token:0123456789ab").run("SELECT 1 AS one")
            _ = await session.run("SELECT 2 AS two")

    asyncio.run(go())

    principals = [
        line.split('"principal":"')[1].split('"')[0]
        for line in log.read_text().splitlines()
    ]
    assert principals == ["token:0123456789ab", "local"]
