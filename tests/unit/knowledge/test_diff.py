from __future__ import annotations

from forbql.firewall import ColumnInfo, ForeignKey, SchemaCatalog, TableInfo
from forbql.knowledge import diff_catalogs

ID = ColumnInfo(name="id", type="integer", nullable=False)
CLIENTS = TableInfo(columns=(ID,), primary_key=("id",))
ACCOUNTS = TableInfo(
    columns=(ID, ColumnInfo(name="client_id", type="integer", nullable=False)),
    primary_key=("id",),
    foreign_keys=(
        ForeignKey(columns=("client_id",), table="public.clients", references=("id",)),
    ),
)
TOTALS = TableInfo(columns=(ID,), view=True, definition="SELECT id FROM accounts")


def catalog(**tables: TableInfo) -> SchemaCatalog:
    return SchemaCatalog(
        default_schema="public",
        tables={f"public.{name}": table for name, table in tables.items()},
    )


def test_the_same_schema_has_no_changes():
    same = catalog(clients=CLIENTS, accounts=ACCOUNTS)

    assert diff_catalogs(same, same) == []


def test_tables_and_views_come_and_go():
    old = catalog(clients=CLIENTS, totals=TOTALS)
    new = catalog(clients=CLIENTS, accounts=ACCOUNTS)

    assert diff_catalogs(old, new) == [
        "+ table public.accounts",
        "- view public.totals",
    ]


def test_columns_come_go_and_change():
    old = catalog(
        clients=CLIENTS.model_copy(
            update={
                "columns": (
                    ID,
                    ColumnInfo(name="email", type="text", nullable=True),
                    ColumnInfo(name="phone", type="text", nullable=False),
                ),
            },
        ),
    )
    new = catalog(
        clients=CLIENTS.model_copy(
            update={
                "columns": (
                    ColumnInfo(name="id", type="bigint", nullable=False),
                    ColumnInfo(name="email", type="text", nullable=False, comment="c"),
                    ColumnInfo(name="region", type="text", nullable=False),
                ),
            },
        ),
    )

    assert diff_catalogs(old, new) == [
        "+ column public.clients.region text",
        "- column public.clients.phone",
        "~ column public.clients.id: type integer -> bigint",
        "~ column public.clients.email: now not null",
        "~ column public.clients.email: comment",
    ]


def test_keys_comments_and_definitions_change():
    old = catalog(clients=CLIENTS, accounts=ACCOUNTS, totals=TOTALS)
    new = catalog(
        clients=CLIENTS.model_copy(update={"comment": "People"}),
        accounts=ACCOUNTS.model_copy(update={"foreign_keys": (), "primary_key": ()}),
        totals=TOTALS.model_copy(update={"definition": "SELECT 1 AS id"}),
    )

    assert diff_catalogs(old, new) == [
        "~ table public.accounts: primary key (id) -> ()",
        "- foreign key public.accounts (client_id) -> public.clients (id)",
        "~ table public.clients: comment",
        "~ view public.totals: definition",
    ]


def test_a_new_default_schema_and_a_view_turned_table_are_changes():
    old = catalog(clients=CLIENTS, totals=TOTALS)
    new = SchemaCatalog(
        default_schema="bank",
        tables={
            "public.clients": CLIENTS,
            "public.totals": TOTALS.model_copy(
                update={"view": False, "definition": None},
            ),
        },
    )

    assert diff_catalogs(old, new) == [
        "~ default schema: public -> bank",
        "~ table public.totals: was a view",
        "~ table public.totals: definition",
    ]
