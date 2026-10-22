from __future__ import annotations

import pytest
from pydantic import ValidationError

from forbql import Engine, Firewall, RuleId, SchemaSnapshot, Violation
from forbql.policy import parse_policy

SCHEMA = {Engine.POSTGRES: "public", Engine.MYSQL: "bank", Engine.SQLITE: "main"}
POLICY = """
version: 1
connections:
  bank:
    engine: {engine}
    profiles:
      analyst:
        tables:
          {schema}.accounts: {{ columns: "*" }}
          {schema}.totals: {{ columns: "*" }}
          {schema}.fingerprints: {{ columns: "*" }}
      hasher:
        functions: {{ allow: [md5] }}
        tables:
          {schema}.fingerprints: {{ columns: "*" }}
      narrow:
        tables:
          {schema}.accounts: {{ columns: "*" }}
"""
TOTALS = "SELECT client_id, sum(balance) AS balance FROM accounts GROUP BY client_id"
FINGERPRINTS = "SELECT id, md5(email_md5) AS email_md5 FROM fingerprints"
ACCOUNT_TOTALS = (
    "SELECT client_id, count(*) AS accounts, sum(balance) AS balance "
    "FROM accounts GROUP BY client_id"
)
PII_POLICY = """
version: 1
connections:
  bank:
    engine: {engine}
    profiles:
      analyst:
        tables:
          {schema}.clients:
            columns: [id, email, phone, passport]
            pii:
              email: {{ class: mask, strategy: partial }}
              phone: {{ class: aggregate_only }}
              passport: {{ class: deny }}
          {schema}.accounts: {{ columns: "*" }}
          {schema}.renamed: {{ columns: "*" }}
          {schema}.leaked: {{ columns: "*" }}
          {schema}.phones: {{ columns: "*" }}
          {schema}.masked: {{ columns: "*" }}
          {schema}.account_totals: {{ columns: "*" }}
"""


def firewall(engine: Engine, views: dict[str, str | None]) -> Firewall:
    schema = SCHEMA[engine]
    snapshot = SchemaSnapshot(
        default_schema=schema,
        tables={
            f"{schema}.accounts": ("id", "client_id", "balance"),
            f"{schema}.totals": ("client_id", "balance"),
            f"{schema}.fingerprints": ("id", "email_md5"),
        },
        views={f"{schema}.{name}": sql for name, sql in views.items()},
    )
    policy = parse_policy(POLICY.format(engine=engine.value, schema=schema))
    return Firewall(policy, {"bank": snapshot})


def rules(found: dict[str, tuple[Violation, ...]]) -> dict[str, list[RuleId]]:
    return {name: [v.rule for v in violations] for name, violations in found.items()}


def test_a_view_calling_allowed_functions_passes(engine: Engine):
    found = firewall(engine, {"totals": TOTALS}).check_views("bank", "analyst")

    assert found == {}


def test_a_function_outside_the_allowlist_inside_a_view_is_found(engine: Engine):
    found = firewall(engine, {"totals": TOTALS, "fingerprints": FINGERPRINTS})

    problems = found.check_views("bank", "analyst")

    schema = SCHEMA[engine]
    assert rules(problems) == {f"{schema}.fingerprints": [RuleId.FUNCTION_NOT_ALLOWED]}
    assert "md5" in problems[f"{schema}.fingerprints"][0].message


def test_the_profile_allowlist_covers_views_too(engine: Engine):
    found = firewall(engine, {"fingerprints": FINGERPRINTS})

    assert found.check_views("bank", "hasher") == {}


def test_views_the_profile_does_not_list_are_not_its_concern(engine: Engine):
    found = firewall(engine, {"fingerprints": FINGERPRINTS})

    assert found.check_views("bank", "narrow") == {}


def test_a_definition_the_role_cannot_read_is_a_problem(engine: Engine):
    found = firewall(engine, {"totals": None}).check_views("bank", "analyst")

    assert rules(found) == {f"{SCHEMA[engine]}.totals": [RuleId.PARSE_ERROR]}


def test_a_create_view_statement_is_checked_by_its_query():
    definition = f"CREATE VIEW fingerprints AS {FINGERPRINTS}"

    found = firewall(Engine.SQLITE, {"fingerprints": definition})

    assert rules(found.check_views("bank", "analyst")) == {
        "main.fingerprints": [RuleId.FUNCTION_NOT_ALLOWED],
    }


def test_without_a_snapshot_there_is_nothing_to_check():
    policy = parse_policy(POLICY.format(engine="postgres", schema="public"))

    assert Firewall(policy).check_views("bank", "analyst") == {}


def test_a_view_must_have_columns():
    with pytest.raises(ValidationError, match="views missing from tables"):
        SchemaSnapshot(
            default_schema="public",
            tables={"public.accounts": ("id",)},
            views={"public.totals": TOTALS},
        )


def pii_firewall(engine: Engine, views: dict[str, str | None]) -> Firewall:
    schema = SCHEMA[engine]
    tables = {
        f"{schema}.clients": ("id", "email", "phone", "passport"),
        f"{schema}.accounts": ("id", "client_id", "balance"),
        f"{schema}.secrets": ("id", "api_key"),
    }
    tables.update({f"{schema}.{name}": ("id",) for name in views})
    snapshot = SchemaSnapshot(
        default_schema=schema,
        tables=tables,
        views={f"{schema}.{name}": sql for name, sql in views.items()},
    )
    policy = parse_policy(PII_POLICY.format(engine=engine.value, schema=schema))
    return Firewall(policy, {"bank": snapshot})


def test_a_view_that_renames_a_denied_column_is_refused(engine: Engine):
    definition = "SELECT id, passport AS name FROM clients"
    found = pii_firewall(engine, {"renamed": definition}).check_views("bank", "analyst")

    schema = SCHEMA[engine]
    assert rules(found) == {f"{schema}.renamed": [RuleId.UNKNOWN_COLUMN]}
    assert "passport" in found[f"{schema}.renamed"][0].message


def test_a_view_that_reads_a_table_the_profile_cannot_see_is_refused(engine: Engine):
    found = pii_firewall(engine, {"leaked": "SELECT api_key FROM secrets"})

    problems = found.check_views("bank", "analyst")

    schema = SCHEMA[engine]
    assert rules(problems) == {f"{schema}.leaked": [RuleId.TABLE_NOT_ALLOWED]}
    assert "secrets" in problems[f"{schema}.leaked"][0].message


def test_account_totals_over_an_allowlisted_table_is_accepted(engine: Engine):
    found = pii_firewall(engine, {"account_totals": ACCOUNT_TOTALS})

    assert found.check_views("bank", "analyst") == {}


def test_a_view_that_selects_an_aggregate_only_column_is_refused(engine: Engine):
    found = pii_firewall(engine, {"phones": "SELECT phone FROM clients"})

    assert rules(found.check_views("bank", "analyst")) == {
        f"{SCHEMA[engine]}.phones": [RuleId.PII_AGGREGATE_ONLY],
    }


def test_a_view_that_passes_a_masked_column_to_a_function_is_refused(engine: Engine):
    found = pii_firewall(
        engine, {"masked": "SELECT upper(email) AS email FROM clients"}
    )

    assert rules(found.check_views("bank", "analyst")) == {
        f"{SCHEMA[engine]}.masked": [RuleId.PII_MASKED],
    }


def test_a_create_view_that_renames_a_denied_column_is_refused():
    definition = "CREATE VIEW renamed AS SELECT id, passport AS name FROM clients"

    found = pii_firewall(Engine.SQLITE, {"renamed": definition})

    assert rules(found.check_views("bank", "analyst")) == {
        "main.renamed": [RuleId.UNKNOWN_COLUMN],
    }
