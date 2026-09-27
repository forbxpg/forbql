"""Describing a table through a session, on the stand.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

import forbql
from forbql import Engine, SessionError
from forbql.knowledge import SAMPLE_FLOOR
from support.corpus import DEMO
from support.stand import READER

if TYPE_CHECKING:
    from pathlib import Path

    from forbql.knowledge import TableDescription

pytestmark = pytest.mark.integration

POLICY = DEMO / "forbql.yaml"


def described(tmp_path: Path, table: str) -> TableDescription:
    async def go() -> TableDescription:
        async with forbql.connect(
            POLICY,
            connection="bank-postgres",
            profile="analyst",
            dsn=READER[Engine.POSTGRES],
            audit_log=tmp_path / "audit.jsonl",
        ) as session:
            return await session.describe(table)

    return asyncio.run(go())


def test_a_table_shows_its_columns_and_how_it_joins(tmp_path: Path):
    found = described(tmp_path, "accounts")

    assert found.table == "public.accounts"
    assert [c.name for c in found.columns][:2] == ["id", "client_id"]
    assert found.columns[0].key
    assert "public.accounts.client_id = public.clients.id" in found.joins


def test_sample_columns_show_frequent_values_and_pii_is_named(tmp_path: Path):
    found = described(tmp_path, "public.clients")

    assert "passport" not in [c.name for c in found.columns]
    assert {c.name: c.pii for c in found.columns}["email"] == "mask"
    assert list(found.samples) == ["region"]
    assert found.samples["region"]


def test_a_hidden_table_and_a_missing_one_answer_alike(tmp_path: Path):
    messages: list[str] = []
    for table in ("public.secrets", "public.nothing"):
        with pytest.raises(SessionError) as refused:
            _ = described(tmp_path, table)
        messages.append(str(refused.value).replace(table, "<table>"))

    assert messages == ["table <table> is not available"] * 2


def test_a_description_and_its_sample_queries_are_audited(tmp_path: Path):
    _ = described(tmp_path, "public.clients")

    records = [
        json.loads(line)
        for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert [r["action"] for r in records] == ["sql.run", "schema.describe"]
    assert f"HAVING COUNT(*) >= {SAMPLE_FLOOR}" in records[0]["sql"]
    assert records[1]["sql"] == "public.clients"
