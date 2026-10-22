"""Catalog rows record a generated column, and an unreadable expression stays null."""

from __future__ import annotations

from forbql.engines.mysql._catalog import COLUMNS as MYSQL_COLUMNS
from forbql.engines.mysql._catalog import column_info as mysql_column
from forbql.engines.postgres._catalog import COLUMNS as POSTGRES_COLUMNS
from forbql.engines.postgres._catalog import column_info as postgres_column


def test_postgres_column_query_reads_the_generation_expression():
    assert "attgenerated" in POSTGRES_COLUMNS
    assert "pg_get_expr" in POSTGRES_COLUMNS


def test_postgres_keeps_a_readable_generation_expression():
    column = postgres_column(
        "pub",
        "text",
        None,
        nullable=True,
        generation=(True, " email "),
    )

    assert column.generated
    assert column.expression == "email"


def test_postgres_marks_an_unreadable_expression_as_generated():
    column = postgres_column(
        "pub",
        "text",
        None,
        nullable=True,
        generation=(True, None),
    )

    assert column.generated
    assert column.expression is None


def test_postgres_ignores_a_default_on_a_stored_column():
    column = postgres_column(
        "email",
        "text",
        "contact",
        nullable=True,
        generation=(False, "now()"),
    )

    assert column.name == "email"
    assert column.comment == "contact"
    assert column.nullable is True
    assert column.generated is False
    assert column.expression is None


def test_mysql_column_query_reads_the_generation_expression():
    folded = MYSQL_COLUMNS.lower()

    assert "generation_expression" in folded
    assert "virtual generated" in folded
    assert "stored generated" in folded


def test_mysql_keeps_a_readable_generation_expression():
    column = mysql_column(
        "pub",
        "varchar(20)",
        "",
        nullable=True,
        generation=(1, " email "),
    )

    assert column.generated
    assert column.expression == "email"
    assert column.comment is None


def test_mysql_marks_an_unreadable_expression_as_generated():
    column = mysql_column(
        "pub",
        "varchar(20)",
        None,
        nullable=0,
        generation=(True, ""),
    )

    assert column.generated
    assert column.nullable is False
    assert column.expression is None


def test_mysql_ignores_an_expression_default():
    column = mysql_column(
        "created",
        "datetime",
        None,
        nullable=True,
        generation=(0, "current_timestamp"),
    )

    assert column.generated is False
    assert column.expression is None
