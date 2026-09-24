"""A session will not open on a role that may do more than read, or on a bad view.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

import forbql
from forbql import Engine, SessionError
from support.corpus import DEMO, SCHEMA
from support.stand import ADMIN, READER, probe_account

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.integration

POLICY = DEMO / "forbql.yaml"
LIVE = (Engine.POSTGRES, Engine.MYSQL)


def open_session(engine: Engine, dsn: str, tmp_path: Path, policy: Path = POLICY):
    async def go() -> tuple[str, ...]:
        async with forbql.connect(
            policy,
            connection=f"bank-{engine}",
            profile="analyst",
            dsn=dsn,
            audit_log=tmp_path / "audit.jsonl",
        ) as session:
            return session.warnings

    return asyncio.run(go())


@pytest.mark.parametrize("engine", LIVE, ids=str)
def test_the_demo_reader_opens_a_session_without_warnings(
    engine: Engine,
    tmp_path: Path,
):
    assert open_session(engine, READER[engine], tmp_path) == ()


@pytest.mark.parametrize("engine", LIVE, ids=str)
def test_the_owner_cannot_open_a_session(engine: Engine, tmp_path: Path):
    with pytest.raises(SessionError, match=f"forbql will not open bank-{engine}"):
        open_session(engine, ADMIN[engine], tmp_path)


@pytest.mark.parametrize(
    ("engine", "grant", "refusal"),
    [
        (
            Engine.POSTGRES,
            "GRANT SELECT, INSERT ON accounts TO forbql_probe",
            "the role may INSERT on public.accounts",
        ),
        (
            Engine.MYSQL,
            "GRANT SELECT, INSERT ON bank.accounts TO 'forbql_probe'@'%'",
            "the account may INSERT on `bank`.`accounts`",
        ),
    ],
    ids=str,
)
def test_a_role_that_may_write_cannot_open_a_session(
    engine: Engine,
    grant: str,
    refusal: str,
    tmp_path: Path,
):
    with probe_account(engine, [grant]) as dsn, pytest.raises(SessionError) as caught:
        open_session(engine, dsn, tmp_path)

    assert f"  - {refusal}" in str(caught.value).splitlines()


@pytest.mark.parametrize("engine", LIVE, ids=str)
def test_a_listed_view_calling_md5_cannot_open_a_session(
    engine: Engine,
    tmp_path: Path,
):
    schema = SCHEMA[engine]
    listed = f'          {schema}.account_totals: {{ columns: "*" }}\n'
    policy = tmp_path / "forbql.yaml"
    policy.write_text(
        POLICY.read_text(encoding="utf-8").replace(
            listed,
            listed + f'          {schema}.client_fingerprints: {{ columns: "*" }}\n',
        ),
        encoding="utf-8",
    )

    with pytest.raises(SessionError) as caught:
        open_session(engine, READER[engine], tmp_path, policy)

    assert str(caught.value).splitlines()[1:] == [
        f"  - view {schema}.client_fingerprints: function md5 is not allowed",
    ]
