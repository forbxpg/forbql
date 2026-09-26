"""The audit chain in the store: appended one at a time, checked end to end.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio

import pytest
from typer.testing import CliRunner

from forbql.audit import AuditRecord, Verification
from forbql.cli import app
from forbql.store import Store
from support.store import STORE_APP, STORE_SUPERUSER, fresh_store, store_sql

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("store")]


@pytest.fixture
def store() -> str:
    return fresh_store()


async def append(store: Store, sql: str) -> AuditRecord:
    return await store.audit.append(
        principal="local",
        connection="bank",
        profile="analyst",
        policy_hash="sha256:x",
        sql=sql,
        executed_sql=sql,
        allowed=True,
        rules=("rule",),
        rows=1,
        size=10,
        truncated=False,
        duration_ms=3,
        error_class=None,
        error_detail="ё and ✓ survive",
    )


def write(count: int) -> list[AuditRecord]:
    async def go() -> list[AuditRecord]:
        async with Store.open(STORE_APP) as store:
            return [await append(store, f"SELECT {n}") for n in range(count)]

    return asyncio.run(go())


def verify() -> Verification:
    async def go() -> Verification:
        async with Store.open(STORE_APP) as store:
            return await store.audit.verify()

    return asyncio.run(go())


def test_records_chain_from_genesis_and_read_back_intact():
    records = write(3)

    assert records[0].previous == "0" * 64
    assert [r.previous for r in records[1:]] == [r.hash for r in records[:2]]
    assert verify() == Verification(records=3)


def test_writers_on_two_connections_keep_one_chain():
    async def writer(tag: str) -> None:
        async with Store.open(STORE_APP) as store:
            for n in range(10):
                _ = await append(store, f"SELECT '{tag}{n}'")

    async def both() -> None:
        _ = await asyncio.gather(writer("a"), writer("b"))

    asyncio.run(both())

    assert verify() == Verification(records=20)
    seqs = store_sql(
        STORE_SUPERUSER,
        "SELECT seq FROM forbql.audit_records ORDER BY seq",
    )
    assert [seq for (seq,) in seqs[0]] == list(range(1, 21))


def test_an_altered_record_is_found():
    write(3)
    store_sql(
        STORE_SUPERUSER,
        "UPDATE forbql.audit_records SET rows = 999 WHERE seq = 2",
    )

    assert verify() == Verification(1, 2, "record altered after it was written")


def test_a_removed_record_is_found():
    write(3)
    store_sql(STORE_SUPERUSER, "DELETE FROM forbql.audit_records WHERE seq = 2")

    assert verify() == Verification(1, 2, "chain broken: a record is missing or moved")


def test_the_cli_verifies_the_store_without_a_path(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FORBQL_STORE_DSN", STORE_APP)
    write(2)

    intact = CliRunner().invoke(app, ["audit", "verify"])
    store_sql(
        STORE_SUPERUSER,
        "UPDATE forbql.audit_records SET sql = 'x' WHERE seq = 1",
    )
    broken = CliRunner().invoke(app, ["audit", "verify"])

    assert intact.exit_code == 0
    assert intact.stdout == "the store's audit chain: intact; 2 record(s)\n"
    assert broken.exit_code == 1
    assert "broken at line 1: record altered" in broken.stdout
