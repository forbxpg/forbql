"""Policy, snapshot and helpers shared by firewall tests."""

from __future__ import annotations

from forbql import Engine, Firewall, RuleId, SchemaSnapshot, Verdict
from forbql.policy import parse_policy

SCHEMA = {Engine.POSTGRES: "public", Engine.MYSQL: "bank", Engine.SQLITE: "main"}
HIDDEN = ("secrets", "api_key", "internal_score", "passport", "description", "currency")

POLICY = """
version: 1
connections:
  bank:
    engine: {engine}
    profiles:
      analyst:
        limits: {{ max_rows: 100, max_joins: 2, max_subquery_depth: 2 }}
        tables:
          {schema}.clients:
            columns: [id, full_name, region, email, phone, passport]
            pii:
              email: {{ class: mask, strategy: partial }}
              phone: {{ class: aggregate_only }}
              passport: {{ class: deny }}
          {schema}.accounts: {{ columns: [id, client_id, balance, status] }}
          {schema}.transactions: {{ columns: "*" }}
      auditor:
        allow_recursive_cte: true
        functions: {{ allow: [md5] }}
        tables:
          {schema}.accounts: {{ columns: "*" }}
          {schema}.clients:
            columns: [id, email]
            pii:
              email: {{ class: mask, strategy: redact }}
"""


def snapshot(engine: Engine) -> SchemaSnapshot:
    schema = SCHEMA[engine]
    return SchemaSnapshot(
        default_schema=schema,
        tables={
            f"{schema}.clients": (
                "id", "full_name", "region", "email", "phone", "passport", "internal_score",
            ),
            f"{schema}.accounts": ("id", "client_id", "currency", "balance", "status"),
            f"{schema}.transactions": ("id", "account_id", "amount", "created_at"),
            f"{schema}.secrets": ("id", "api_key"),
        },
    )  # fmt: skip


def make_firewall(engine: Engine, *, with_schema: bool = True) -> Firewall:
    policy = parse_policy(POLICY.format(engine=engine.value, schema=SCHEMA[engine]))
    return Firewall(policy, {"bank": snapshot(engine)} if with_schema else None)


def check(firewall: Firewall, sql: str, profile: str = "analyst") -> Verdict:
    return firewall.check(sql, connection="bank", profile=profile)


def rules(verdict: Verdict) -> set[RuleId]:
    return {violation.rule for violation in verdict.violations}
