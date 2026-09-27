from __future__ import annotations

from forbql.firewall import ColumnInfo, Firewall, ForeignKey, SchemaCatalog, TableInfo
from forbql.knowledge import ColumnDescription, describe, sample_query
from forbql.policy import Engine, parse_policy

CATALOG = SchemaCatalog(
    default_schema="public",
    tables={
        "public.clients": TableInfo(
            columns=(
                ColumnInfo(name="id", type="integer", nullable=False),
                ColumnInfo(name="full_name", type="text", nullable=False),
                ColumnInfo(name="passport", type="text", nullable=False),
                ColumnInfo(name="region", type="text", nullable=False, comment="Code"),
            ),
            primary_key=("id",),
            comment="People who bank with us",
        ),
        "public.accounts": TableInfo(
            columns=(
                ColumnInfo(name="id", type="integer", nullable=False),
                ColumnInfo(name="client_id", type="integer", nullable=False),
                ColumnInfo(name="balance", type="numeric", nullable=True),
            ),
            primary_key=("id",),
            foreign_keys=(
                ForeignKey(
                    columns=("client_id",),
                    table="public.clients",
                    references=("id",),
                ),
            ),
        ),
        "public.salaries": TableInfo(
            columns=(ColumnInfo(name="amount", type="numeric", nullable=False),),
        ),
    },
)
POLICY = parse_policy("""
version: 1
connections:
  bank:
    engine: postgres
    profiles:
      analyst:
        tables:
          public.clients:
            columns: [id, full_name, region]
            pii: { full_name: { class: mask, strategy: redact } }
            samples: [region]
          public.accounts: { columns: "*" }
      hr:
        tables:
          public.salaries: { columns: "*" }
          public.clients: { columns: [id] }
""")
FIREWALL = Firewall(POLICY, {"bank": CATALOG.snapshot()})


def seen_by(profile: str, table: str):
    return describe(
        CATALOG,
        FIREWALL.visible("bank", profile),
        POLICY.profile("bank", profile).tables,
        table,
    )


def test_a_table_shows_its_columns_keys_and_joins():
    found = seen_by("analyst", "public.accounts")

    assert found is not None
    assert [(c.name, c.key) for c in found.columns] == [
        ("id", True),
        ("client_id", False),
        ("balance", False),
    ]
    assert found.joins == ("public.accounts.client_id = public.clients.id",)


def test_hidden_columns_are_absent_and_pii_is_named():
    found = seen_by("analyst", "clients")

    assert found is not None
    assert found.table == "public.clients"
    assert found.comment == "People who bank with us"
    assert found.columns == (
        ColumnDescription(
            name="id",
            type="integer",
            nullable=False,
            comment=None,
            key=True,
            pii=None,
        ),
        ColumnDescription(
            name="full_name",
            type="text",
            nullable=False,
            comment=None,
            key=False,
            pii="mask",
        ),
        ColumnDescription(
            name="region",
            type="text",
            nullable=False,
            comment="Code",
            key=False,
            pii=None,
        ),
    )
    assert found.joins == ("public.accounts.client_id = public.clients.id",)


def test_a_join_to_a_hidden_table_is_not_shown():
    found = seen_by("hr", "public.clients")

    assert found is not None
    assert [c.name for c in found.columns] == ["id"]
    assert found.joins == ()


def test_a_hidden_table_and_a_missing_one_answer_alike():
    assert seen_by("analyst", "public.salaries") is None
    assert seen_by("analyst", "public.loans") is None


def test_the_sample_query_keeps_rare_values_out():
    query = sample_query("public.clients", "region", Engine.POSTGRES)

    assert query == (
        'SELECT "region", COUNT(*) AS n FROM public.clients GROUP BY "region" '
        "HAVING COUNT(*) >= 5 ORDER BY n DESC NULLS LAST LIMIT 10"
    )
