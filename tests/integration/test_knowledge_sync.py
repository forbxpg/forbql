"""Loading a knowledge file through the session and the CLI, on the stand.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from forbql import Engine, SessionError
from forbql.cli import app
from forbql.session import KnowledgeSync, reindex, sync_knowledge, sync_schema
from forbql.store import SecretKey, Store
from support.knowledge import LIVE_KNOWLEDGE, LIVE_POLICY
from support.stand import READER, as_owner
from support.store import STORE_APP, fresh_store

if TYPE_CHECKING:
    from pathlib import Path

    from forbql.store import StoredTerm

pytestmark = pytest.mark.integration

CONNECTION = "bank-postgres"
KEY = SecretKey.generate()
runner = CliRunner()


@pytest.fixture
def policy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    path = tmp_path / "forbql.yaml"
    _ = path.write_text(LIVE_POLICY, encoding="utf-8")
    monkeypatch.setenv("FORBQL_STORE_DSN", fresh_store())
    monkeypatch.setenv("FORBQL_SECRET_KEY", KEY)
    monkeypatch.setenv("FORBQL_POLICY", str(path))

    async def go() -> None:
        async with Store.open(STORE_APP, key=SecretKey.load(KEY, None)) as opened:
            await opened.add_connection(
                CONNECTION,
                Engine.POSTGRES,
                READER[Engine.POSTGRES],
            )

    asyncio.run(go())
    return path


@pytest.fixture
def synced(policy: Path) -> Path:
    _ = asyncio.run(sync_schema(policy, connection=CONNECTION))
    return policy


def load(policy: Path, text: str = LIVE_KNOWLEDGE) -> KnowledgeSync:
    path = policy.parent / "knowledge.yaml"
    _ = path.write_text(text, encoding="utf-8")
    return asyncio.run(sync_knowledge(policy, connection=CONNECTION, path=path))


def stored_terms() -> list[StoredTerm]:
    async def go() -> list[StoredTerm]:
        async with Store.open(STORE_APP) as store:
            return await store.knowledge.terms(CONNECTION)

    return asyncio.run(go())


def test_a_sync_loads_every_entry_and_says_who_sees_it(synced: Path):
    done = load(synced)

    assert done.change.added == (
        "glossary 'open account'",
        "glossary 'fiscal year'",
        "example 'Money on accounts per currency'",
        "example 'Deposits per region'",
    )
    assert done.change.embedded == 4
    seen = {r.label: r.seen for r in done.reach}
    assert seen == {
        "glossary 'open account'": ("analyst",),
        "glossary 'fiscal year'": ("analyst", "teller"),
        "example 'Money on accounts per currency'": ("analyst", "teller"),
        "example 'Deposits per region'": ("analyst",),
    }
    assert [t.table for t in stored_terms()] == [None, "public.accounts"]


def test_a_sync_without_changes_embeds_nothing(synced: Path):
    _ = load(synced)

    again = load(synced)

    assert (again.change.added, again.change.changed, again.change.embedded) == (
        (),
        (),
        0,
    )


def test_the_file_is_the_source_of_truth(synced: Path):
    _ = load(synced)
    edited = LIVE_KNOWLEDGE.replace("Starts on the first of April.", "Starts in July.")
    edited = edited[: edited.index("  - question: Deposits per region")]

    done = load(synced, edited)

    assert done.change.changed == ("glossary 'fiscal year'",)
    assert done.change.removed == ("example 'Deposits per region'",)
    assert done.change.embedded == 1


def test_an_entry_no_profile_sees_keeps_the_store_as_it_was(synced: Path):
    _ = load(synced)
    # Neither profile lists the view account_totals, though the schema holds it.
    leaky = (
        LIVE_KNOWLEDGE.replace("Starts on", "Begins on")
        + "  - question: Totals per client\n"
        + "    sql: SELECT client_id, balance FROM account_totals\n"
    )

    with pytest.raises(SessionError, match="no profile may see") as refused:
        _ = load(synced, leaky)

    assert "example 'Totals per client': analyst: it names account_totals" in str(
        refused.value,
    )
    assert "Starts on" in next(t.definition for t in stored_terms() if t.sql is None)


def test_a_broken_expression_is_refused(synced: Path):
    broken = LIVE_KNOWLEDGE.replace(
        "sql: status = 'open'",
        "sql: count(*) FROM secrets --",
    )

    with pytest.raises(SessionError, match="not one expression"):
        _ = load(synced, broken)
    assert stored_terms() == []


def test_knowledge_needs_a_synced_schema(policy: Path):
    with pytest.raises(SessionError, match="no synced schema"):
        _ = load(policy)


def test_reindex_embeds_the_knowledge_too(synced: Path):
    _ = load(synced)

    done = asyncio.run(reindex(synced, connection=CONNECTION))

    schema_documents = done.embedded - 4
    assert schema_documents > 0


def test_the_cli_syncs_and_refuses(synced: Path):
    path = synced.parent / "knowledge.yaml"
    _ = path.write_text(LIVE_KNOWLEDGE, encoding="utf-8")
    bad = synced.parent / "bad.yaml"
    _ = bad.write_text("glossary: [{term: t}]", encoding="utf-8")

    done = runner.invoke(app, ["knowledge", "sync", CONNECTION, str(path)])
    refused = runner.invoke(app, ["knowledge", "sync", CONNECTION, str(bad)])

    assert done.exit_code == 0, done.stderr
    assert done.stdout.splitlines()[0] == (
        f"{CONNECTION}: 4 added, 0 changed, 0 removed; 4 embedded"
    )
    assert "  glossary 'fiscal year': analyst, teller" in done.stdout.splitlines()
    assert refused.exit_code == 2
    assert "definition" in refused.stderr


def test_a_schema_sync_names_knowledge_no_profile_sees_any_more(synced: Path):
    noted = (
        "glossary:\n  - term: noted account\n    definition: Has a note.\n"
        "    table: accounts\n    sql: note IS NOT NULL\n"
    )
    as_owner(Engine.POSTGRES, ["ALTER TABLE accounts ADD COLUMN note text"])
    try:
        _ = asyncio.run(sync_schema(synced, connection=CONNECTION))
        _ = load(synced, noted)
    finally:
        as_owner(Engine.POSTGRES, ["ALTER TABLE accounts DROP COLUMN IF EXISTS note"])

    after = asyncio.run(sync_schema(synced, connection=CONNECTION))
    cli = runner.invoke(app, ["schema", "sync", CONNECTION])

    assert after.unseen == ("glossary 'noted account'",)
    assert [t.term for t in stored_terms()] == ["noted account"]
    assert cli.stdout.splitlines()[-2:] == [
        "no profile may see these any more; fix the knowledge file:",
        "  glossary 'noted account'",
    ]
