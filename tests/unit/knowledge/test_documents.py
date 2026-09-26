from __future__ import annotations

from forbql.firewall import ColumnInfo, SchemaCatalog, TableInfo
from forbql.knowledge import SearchDocument, documents


def test_a_table_and_each_of_its_columns_are_documents():
    catalog = SchemaCatalog(
        default_schema="bank",
        tables={
            "bank.loan_payments": TableInfo(
                columns=(
                    ColumnInfo(name="due_date", type="date", nullable=False),
                    ColumnInfo(
                        name="penalty",
                        type="numeric",
                        nullable=True,
                        comment="Late payment fine",
                    ),
                ),
                comment="Scheduled and actual loan repayments",
            ),
        },
    )

    assert documents(catalog) == [
        SearchDocument(
            table="bank.loan_payments",
            column="",
            body="loan payments: Scheduled and actual loan repayments",
        ),
        SearchDocument(
            table="bank.loan_payments",
            column="due_date",
            body="loan payments due date",
        ),
        SearchDocument(
            table="bank.loan_payments",
            column="penalty",
            body="loan payments penalty (Late payment fine)",
        ),
    ]


def test_the_hash_follows_the_text():
    one = SearchDocument(table="t", column="", body="a")

    assert one.body_hash == SearchDocument(table="u", column="c", body="a").body_hash
    assert one.body_hash != SearchDocument(table="t", column="", body="b").body_hash
