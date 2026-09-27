"""Names compared as the database compares them: SQLite ignores case, PostgreSQL does not."""

from __future__ import annotations

import pytest
from sqlglot.schema import MappingSchema

from forbql import Firewall, RuleId, SchemaSnapshot
from forbql.firewall._steps import _columns
from forbql.policy import parse_policy
from support.firewall import rules

POLICY = """
version: 1
connections:
  shop:
    engine: {engine}
    profiles:
      clerk:
        tables:
          {tables}
"""

CAMEL = """{schema}.Clients:
            columns: [Id, FullName, Email, Passport]
            pii:
              Email: {{ class: mask, strategy: partial }}
              Passport: {{ class: deny }}"""


def firewall(engine: str, schema: str, tables: str = CAMEL) -> Firewall:
    policy = parse_policy(
        POLICY.format(engine=engine, tables=tables.format(schema=schema)),
    )
    snapshot = SchemaSnapshot(
        default_schema=schema,
        tables={
            f"{schema}.Clients": ("Id", "FullName", "Email", "Passport"),
            f"{schema}.Secrets": ("Id", "ApiKey"),
        },
    )
    return Firewall(policy, {"shop": snapshot})


def sqlite(sql: str, tables: str = CAMEL):
    return firewall("sqlite", "main", tables).check(
        sql,
        connection="shop",
        profile="clerk",
    )


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT Id, FullName FROM Clients",
        "SELECT id, fullname FROM clients",
        'SELECT "ID", "FULLNAME" FROM "CLIENTS"',
        "SELECT c.FullName FROM main.clients AS c",
    ],
)
def test_sqlite_finds_a_name_in_any_case(sql: str):
    verdict = sqlite(sql)

    assert verdict.allowed, verdict.violations


def test_a_policy_may_name_tables_in_another_case():
    lower = "{schema}.clients: {{ columns: [id, fullname] }}"

    assert sqlite("SELECT FullName FROM Clients", lower).allowed
    assert rules(sqlite("SELECT Email FROM Clients", lower)) == {
        RuleId.UNKNOWN_COLUMN,
    }


@pytest.mark.parametrize("name", ["Secrets", "secrets", '"SECRETS"'])
def test_a_hidden_table_stays_hidden_in_every_case(name: str):
    assert rules(sqlite(f"SELECT count(*) FROM {name}")) == {RuleId.TABLE_NOT_ALLOWED}


@pytest.mark.parametrize("name", ["Passport", "passport", '"PASSPORT"'])
def test_a_denied_column_stays_denied_in_every_case(name: str):
    assert rules(sqlite(f"SELECT {name} FROM Clients")) == {RuleId.UNKNOWN_COLUMN}


@pytest.mark.parametrize("name", ["Email", "email", '"EMAIL"'])
def test_a_masked_column_is_masked_in_every_case(name: str):
    verdict = sqlite(f"SELECT {name} FROM Clients")

    assert verdict.allowed
    assert len(verdict.masks) == 1


def test_callers_get_the_names_the_database_uses():
    visible = firewall("sqlite", "main").visible("shop", "clerk")

    assert visible == {"main.Clients": ("Id", "FullName", "Email")}


def postgres(sql: str):
    return firewall("postgres", "public").check(sql, connection="shop", profile="clerk")


def test_postgres_finds_quoted_names_and_tells_them_apart():
    assert postgres('SELECT "FullName" FROM "Clients"').allowed
    assert rules(postgres("SELECT fullname FROM clients")) == {
        RuleId.TABLE_NOT_ALLOWED,
    }


@pytest.mark.parametrize(
    ("engine", "schema"),
    [("postgres", "public"), ("sqlite", "main")],
)
def test_a_star_over_a_mixed_case_table_is_the_visible_columns(
    engine: str,
    schema: str,
):
    verdict = firewall(engine, schema).check(
        'SELECT * FROM "Clients"',
        connection="shop",
        profile="clerk",
    )

    assert verdict.allowed
    assert verdict.sql is not None
    assert "*" not in verdict.sql
    assert "passport" not in verdict.sql.lower()


def test_a_string_in_double_quotes_is_told_to_use_single_ones():
    verdict = sqlite('SELECT Id FROM Clients WHERE FullName = "Ann Lee"')

    assert rules(verdict) == {RuleId.UNKNOWN_COLUMN}
    hint = verdict.violations[0].hint or ""
    assert hint.endswith("strings take single quotes; double quotes name a column")


def test_a_star_the_qualifier_could_not_expand_is_refused(
    monkeypatch: pytest.MonkeyPatch,
):
    # As before names kept their case: the qualifier lowers "Clients", finds no such
    # table and leaves the * in place.
    def lowering(schema: dict[str, object], *, dialect: str, normalize: bool):
        del normalize
        return MappingSchema(schema, dialect=dialect)

    monkeypatch.setattr(_columns, "MappingSchema", lowering)

    assert rules(postgres('SELECT * FROM "Clients"')) == {RuleId.INTERNAL_ERROR}
