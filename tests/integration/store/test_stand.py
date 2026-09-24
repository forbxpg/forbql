"""The store's roles on the local stand, before any migration.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncpg
import pytest

from support.store import STORE_APP, STORE_OWNER, empty_store, store_sql

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("empty")]


@pytest.fixture
def empty() -> None:
    empty_store()


def test_the_owner_may_create_tables_in_the_schema():
    store_sql(STORE_OWNER, "CREATE TABLE forbql.probe (id integer)")


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE forbql.probe (id integer)",
        "CREATE TABLE public.probe (id integer)",
    ],
)
def test_the_runtime_role_may_create_nothing(sql: str):
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        store_sql(STORE_APP, sql)
