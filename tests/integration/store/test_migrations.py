"""The store's schema: migrations, the rights they grant, and the revision check.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import asyncpg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import create_async_engine
from typer.testing import CliRunner

from forbql.cli import app
from forbql.store import StoreError, check_revision, head, migrate
from forbql.store._tables import metadata
from forbql.store._url import sqlalchemy_url
from support.store import STORE_APP, STORE_OWNER, empty_store, store_sql

if TYPE_CHECKING:
    from sqlalchemy import Connection

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("empty")]

GENESIS = "0" * 64


@pytest.fixture
def empty() -> None:
    empty_store()


def revision_check(dsn: str) -> None:
    async def go() -> None:
        engine = create_async_engine(sqlalchemy_url(dsn))
        try:
            async with engine.connect() as connection:
                await check_revision(connection)
        finally:
            await engine.dispose()

    asyncio.run(go())


def test_migrating_creates_the_default_workspace_and_its_audit_head():
    assert migrate(STORE_OWNER) == head()

    rows = store_sql(
        STORE_APP,
        "SELECT name FROM forbql.workspaces",
        "SELECT seq, hash FROM forbql.audit_heads",
    )

    assert rows == [[("default",)], [(0, GENESIS)]]


def test_migrating_twice_changes_nothing():
    migrate(STORE_OWNER)

    assert migrate(STORE_OWNER) == head()


def forbql_only(name: str | None, kind: str, _parent: object) -> bool:
    return kind != "schema" or name == "forbql"


def differences(connection: Connection) -> list[object]:
    context = MigrationContext.configure(
        connection,
        opts={
            "include_schemas": True,
            "version_table_schema": "forbql",
            "include_name": forbql_only,
        },
    )
    return list(compare_metadata(context, metadata))


def test_the_migrations_build_exactly_the_tables():
    migrate(STORE_OWNER)

    async def go() -> list[object]:
        engine = create_async_engine(sqlalchemy_url(STORE_OWNER))
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(differences)
        finally:
            await engine.dispose()

    assert asyncio.run(go()) == []


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE forbql.audit_records SET rows = 0",
        "DELETE FROM forbql.audit_records",
        "TRUNCATE forbql.audit_records",
        "DELETE FROM forbql.audit_heads",
        "UPDATE forbql.workspaces SET name = 'other'",
        "CREATE TABLE forbql.probe (id integer)",
        "ALTER TABLE forbql.connections ADD COLUMN probe integer",
        "UPDATE forbql.alembic_version SET version_num = 'x'",
    ],
)
def test_the_runtime_role_cannot_rewrite_history_or_the_schema(sql: str):
    migrate(STORE_OWNER)

    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        store_sql(STORE_APP, sql)


def test_the_runtime_role_may_manage_connections():
    migrate(STORE_OWNER)

    store_sql(
        STORE_APP,
        """
        INSERT INTO forbql.connections (workspace_id, name, engine)
        SELECT id, 'bank', 'postgres' FROM forbql.workspaces
        """,
        "UPDATE forbql.connections SET engine = 'mysql'",
        "DELETE FROM forbql.connections",
    )


def test_a_migrated_store_passes_the_revision_check():
    migrate(STORE_OWNER)

    revision_check(STORE_APP)


def test_a_store_without_a_schema_is_refused():
    with pytest.raises(StoreError, match="at nothing, this forbql needs"):
        revision_check(STORE_APP)


def test_a_store_at_another_revision_is_refused():
    migrate(STORE_OWNER)
    store_sql(STORE_OWNER, "UPDATE forbql.alembic_version SET version_num = '0000'")

    with pytest.raises(StoreError, match="run `forbql store migrate`"):
        revision_check(STORE_APP)


def test_the_cli_migrates_as_the_owner(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FORBQL_STORE_OWNER_DSN", STORE_OWNER)

    result = CliRunner().invoke(app, ["store", "migrate"])

    assert result.exit_code == 0
    assert result.stdout == f"the store is at revision {head()}\n"


def test_the_cli_needs_the_owner_dsn(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("FORBQL_STORE_OWNER_DSN", raising=False)

    result = CliRunner().invoke(app, ["store", "migrate"])

    assert result.exit_code == 2
    assert "FORBQL_STORE_OWNER_DSN" in result.stderr
