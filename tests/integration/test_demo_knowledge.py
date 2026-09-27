"""The demo knowledge file loads for the demo bank, and the analyst sees all of it.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from forbql import Engine
from forbql.session import sync_knowledge, sync_schema
from forbql.store import SecretKey, Store
from support.corpus import DEMO
from support.stand import READER
from support.store import STORE_APP, fresh_store

if TYPE_CHECKING:
    from forbql.session import KnowledgeSync

pytestmark = pytest.mark.integration

KEY = SecretKey.generate()


def test_the_demo_knowledge_reaches_the_analyst(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FORBQL_STORE_DSN", fresh_store())
    monkeypatch.setenv("FORBQL_SECRET_KEY", KEY)

    async def go() -> KnowledgeSync:
        async with Store.open(STORE_APP, key=SecretKey.load(KEY, None)) as opened:
            await opened.add_connection(
                "bank-postgres",
                Engine.POSTGRES,
                READER[Engine.POSTGRES],
            )
        policy = DEMO / "forbql.yaml"
        _ = await sync_schema(policy, connection="bank-postgres")
        return await sync_knowledge(
            policy,
            connection="bank-postgres",
            path=DEMO / "knowledge.yaml",
        )

    done = asyncio.run(go())

    assert len(done.reach) == 7
    assert all(found.seen == ("analyst",) for found in done.reach)
