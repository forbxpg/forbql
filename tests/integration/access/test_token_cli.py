"""`forbql token` against the store on the local stand.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio

import pytest
from typer.testing import CliRunner

from forbql.access import Capability, TokenParts, authenticate
from forbql.cli import app
from forbql.store import Store
from support.corpus import DEMO
from support.store import STORE_APP, fresh_store

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("store")]

runner = CliRunner()


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORBQL_STORE_DSN", fresh_store())
    monkeypatch.setenv("FORBQL_POLICY", str(DEMO / "forbql.yaml"))


def token(*args: str):
    return runner.invoke(app, ["token", *args])


def create(name: str = "ci", *grants: str):
    return token(
        "create",
        name,
        *[f"--grant={g}" for g in grants or ("bank-postgres:analyst:sql.run",)],
    )


def test_create_prints_a_working_token_alone_on_standard_output():
    result = create("ci", "bank-postgres:analyst:sql.check,sql.run")

    assert result.exit_code == 0
    value = result.stdout.strip()
    parts = TokenParts.parse(value)
    assert parts is not None
    assert f"token {parts.token_id} (ci), expires " in result.stderr

    async def present() -> bool:
        async with Store.open(STORE_APP) as store:
            principal = await authenticate(store, value)
        return principal.may(
            Capability.SQL_RUN,
            connection="bank-postgres",
            profile="analyst",
        )

    assert asyncio.run(present())


@pytest.mark.parametrize(
    ("grant", "message"),
    [
        ("bank-postgres:admin:sql.run", "admin"),
        ("nowhere:analyst:sql.run", "nowhere"),
        ("bank-postgres:analyst:sql.drop", "unknown capability"),
    ],
)
def test_a_grant_the_policy_does_not_know_is_refused(grant: str, message: str):
    result = create("ci", grant)

    assert result.exit_code == 2
    assert message in result.stderr
    assert not result.stdout


def test_a_lifetime_past_a_year_is_refused():
    result = token(
        "create",
        "ci",
        "--grant=bank-postgres:analyst:sql.run",
        "--days=400",
    )

    assert result.exit_code == 2
    assert "at most 365 days" in result.stderr


def test_list_shows_state_and_grants_never_the_secret():
    value = create("ci").stdout.strip()

    listed = token("list").stdout

    parts = TokenParts.parse(value)
    assert parts is not None
    assert listed.startswith(f"{parts.token_id}  ci  until ")
    assert listed.rstrip().endswith("bank-postgres:analyst:sql.run")
    assert parts.secret not in listed


def test_revoke_is_final():
    value = create("ci").stdout.strip()
    parts = TokenParts.parse(value)
    assert parts is not None

    first = token("revoke", parts.token_id)
    again = token("revoke", parts.token_id)

    assert first.stdout == f"revoked {parts.token_id}\n"
    assert again.exit_code == 1
    assert "  revoked  " in token("list").stdout
