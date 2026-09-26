from __future__ import annotations

from forbql.engines._describe import Relation, assemble
from forbql.firewall import ColumnInfo, ForeignKey


def column(name: str) -> ColumnInfo:
    return ColumnInfo(name=name, type="integer", nullable=False)


def test_keys_that_name_hidden_columns_or_tables_are_left_out():
    catalog = assemble(
        "public",
        {
            "public.clients": Relation(
                columns=[column("id")],
                primary_key=("passport",),
                comment="",
            ),
            "public.accounts": Relation(
                columns=[column("id"), column("client_id")],
                primary_key=("id",),
                foreign_keys=[
                    ForeignKey(
                        columns=("client_id",),
                        table="public.clients",
                        references=("id",),
                    ),
                    ForeignKey(
                        columns=("id",),
                        table="public.secrets",
                        references=("id",),
                    ),
                ],
            ),
            "public.secrets": Relation(),
        },
    )

    assert set(catalog.tables) == {"public.clients", "public.accounts"}
    assert catalog.tables["public.clients"].primary_key == ()
    assert catalog.tables["public.clients"].comment is None
    assert catalog.tables["public.accounts"].foreign_keys == (
        ForeignKey(columns=("client_id",), table="public.clients", references=("id",)),
    )
