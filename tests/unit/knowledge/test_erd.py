from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from forbql.engines import connect
from forbql.firewall import ColumnInfo, Firewall, SchemaCatalog, TableInfo
from forbql.knowledge import MAX_TABLES, erd
from forbql.policy import Engine, load_policy
from support.corpus import DEMO
from support.demo_db import build_demo_sqlite

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def demo(tmp_path: Path) -> tuple[SchemaCatalog, dict[str, tuple[str, ...]]]:
    async def describe() -> SchemaCatalog:
        engine = await connect(Engine.SQLITE, str(build_demo_sqlite(tmp_path)))
        try:
            return await engine.describe()
        finally:
            await engine.close()

    catalog = asyncio.run(describe())
    firewall = Firewall(
        load_policy(DEMO / "forbql.yaml"),
        {"bank-sqlite": catalog.snapshot()},
    )
    return catalog, firewall.visible("bank-sqlite", "analyst")


def test_the_diagram_holds_what_the_profile_sees_and_no_more(
    demo: tuple[SchemaCatalog, dict[str, tuple[str, ...]]],
):
    diagram = erd(*demo)

    assert diagram.startswith("erDiagram\n")
    assert '    main_clients["main.clients"] {' in diagram
    assert "        INTEGER id PK" in diagram
    assert "        INTEGER client_id FK" in diagram
    assert "passport" not in diagram
    assert "secrets" not in diagram
    assert '    main_clients ||--o{ main_accounts : "client_id"' in diagram
    assert '    main_accounts ||--o{ main_transactions : "account_id"' in diagram


def test_a_diagram_around_a_table_reaches_its_neighbours_only(
    demo: tuple[SchemaCatalog, dict[str, tuple[str, ...]]],
):
    diagram = erd(*demo, around=["clients"])

    assert "main_accounts[" in diagram
    assert "main_transactions[" not in diagram
    assert "main_transactions[" in erd(*demo, around=["clients"], depth=2)


def test_a_hidden_table_cannot_be_the_centre(
    demo: tuple[SchemaCatalog, dict[str, tuple[str, ...]]],
):
    with pytest.raises(ValueError, match=r"no visible table main\.secrets"):
        erd(*demo, around=["secrets"])


def test_a_large_schema_needs_a_centre():
    column = ColumnInfo(name="id", type="integer", nullable=False)
    names = [f"public.t{n}" for n in range(MAX_TABLES + 1)]
    catalog = SchemaCatalog(
        default_schema="public",
        tables={name: TableInfo(columns=(column,)) for name in names},
    )
    visible = dict.fromkeys(names, ("id",))

    with pytest.raises(ValueError, match="too many for one diagram"):
        erd(catalog, visible)
    assert "public_t0[" in erd(catalog, visible, around=["t0"])


def test_types_become_mermaid_words():
    catalog = SchemaCatalog(
        default_schema="public",
        tables={
            "public.accounts": TableInfo(
                columns=(
                    ColumnInfo(name="balance", type="numeric(14,2)", nullable=False),
                    ColumnInfo(
                        name="opened",
                        type="timestamp with time zone",
                        nullable=False,
                    ),
                ),
            ),
        },
    )

    diagram = erd(catalog, {"public.accounts": ("balance", "opened")})

    assert "        numeric_14_2 balance" in diagram
    assert "        timestamp_with_time_zone opened" in diagram


def test_a_quoted_column_name_keeps_the_diagram_valid():
    catalog = SchemaCatalog(
        default_schema="public",
        tables={
            "public.people": TableInfo(
                columns=(
                    ColumnInfo(name="first name", type="text", nullable=False),
                    ColumnInfo(name="order-id", type="integer", nullable=False),
                ),
                primary_key=("order-id",),
            ),
        },
    )

    diagram = erd(catalog, {"public.people": ("first name", "order-id")})

    assert '        text first_name "first name"' in diagram
    assert '        integer order_id PK "order-id"' in diagram
