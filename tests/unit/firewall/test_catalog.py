from __future__ import annotations

import pytest
from pydantic import ValidationError

from forbql.firewall import ColumnInfo, ForeignKey, SchemaCatalog, TableInfo

CLIENTS = TableInfo(
    columns=(
        ColumnInfo(name="id", type="integer", nullable=False),
        ColumnInfo(name="email", type="text", nullable=False, comment="Contact"),
    ),
    primary_key=("id",),
    comment="Bank clients",
)
ACCOUNTS = TableInfo(
    columns=(
        ColumnInfo(name="id", type="integer", nullable=False),
        ColumnInfo(name="client_id", type="integer", nullable=False),
    ),
    primary_key=("id",),
    foreign_keys=(
        ForeignKey(columns=("client_id",), table="public.clients", references=("id",)),
    ),
)
TOTALS = TableInfo(
    columns=(ColumnInfo(name="client_id", type="integer", nullable=True),),
    view=True,
    definition="SELECT client_id FROM accounts",
)


def catalog(**tables: TableInfo) -> SchemaCatalog:
    return SchemaCatalog(
        default_schema="public",
        tables={f"public.{name}": table for name, table in tables.items()},
    )


def test_the_snapshot_keeps_names_and_view_definitions():
    snapshot = catalog(clients=CLIENTS, accounts=ACCOUNTS, totals=TOTALS).snapshot()

    assert snapshot.default_schema == "public"
    assert snapshot.tables == {
        "public.clients": ("id", "email"),
        "public.accounts": ("id", "client_id"),
        "public.totals": ("client_id",),
    }
    assert snapshot.views == {"public.totals": "SELECT client_id FROM accounts"}


def test_a_foreign_key_must_point_at_a_table_in_the_catalog():
    with pytest.raises(ValidationError, match=r"foreign key to public\.clients"):
        catalog(accounts=ACCOUNTS)


def test_a_primary_key_must_name_its_columns():
    broken = CLIENTS.model_copy(update={"primary_key": ("uuid",)})

    with pytest.raises(ValidationError, match="primary key names missing columns"):
        catalog(clients=broken)


def test_the_hash_follows_the_content_only():
    first = catalog(clients=CLIENTS, accounts=ACCOUNTS)
    reordered = catalog(accounts=ACCOUNTS, clients=CLIENTS)
    retyped = catalog(
        clients=CLIENTS.model_copy(
            update={
                "columns": (
                    CLIENTS.columns[0],
                    CLIENTS.columns[1].model_copy(update={"type": "varchar(200)"}),
                ),
            },
        ),
        accounts=ACCOUNTS,
    )

    assert first.content_hash() == reordered.content_hash()
    assert first.content_hash() != retyped.content_hash()


def test_a_view_replaced_by_a_table_stays_unseen_until_synced():
    reviewed = catalog(clients=CLIENTS, totals=TOTALS).snapshot()
    replaced = catalog(
        clients=CLIENTS,
        totals=TOTALS.model_copy(update={"view": False, "definition": None}),
    ).snapshot()

    assert set(replaced.within(reviewed).tables) == {"public.clients"}
    assert set(reviewed.within(replaced).tables) == {"public.clients"}
