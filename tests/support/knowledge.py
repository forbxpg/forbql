"""A small bank, a policy with two profiles over it, and a firewall for both."""

from __future__ import annotations

from forbql.firewall import ColumnInfo, Firewall, SchemaCatalog, TableInfo
from forbql.policy import parse_policy

CONNECTION = "bank"


def _table(*names: str) -> TableInfo:
    return TableInfo(
        columns=tuple(ColumnInfo(name=n, type="text", nullable=True) for n in names),
    )


CATALOG = SchemaCatalog(
    default_schema="public",
    tables={
        "public.clients": _table("id", "full_name", "passport", "region"),
        "public.accounts": _table("id", "client_id", "balance", "status"),
        "public.salaries": _table("id", "amount"),
    },
)

POLICY = parse_policy(f"""
version: 1
connections:
  {CONNECTION}:
    engine: postgres
    profiles:
      analyst:
        tables:
          public.clients: {{ columns: [id, full_name, region] }}
          public.accounts: {{ columns: "*" }}
      hr:
        tables:
          public.salaries: {{ columns: "*" }}
          public.clients: {{ columns: [id] }}
""")

FIREWALL = Firewall(POLICY, {CONNECTION: CATALOG.snapshot()})

LIVE_POLICY = """
version: 1
connections:
  bank-postgres:
    engine: postgres
    profiles:
      analyst:
        tables:
          public.clients:
            columns: [id, full_name, email, phone, passport, region, created_at]
            pii:
              email: { class: mask, strategy: partial }
              phone: { class: aggregate_only }
              passport: { class: deny }
          public.accounts: { columns: "*" }
          public.transactions: { columns: "*" }
      teller:
        tables:
          public.accounts: { columns: [id, client_id, currency, balance] }
"""
"""The demo bank's analyst, and a teller who sees four columns of accounts."""

LIVE_KNOWLEDGE = """
glossary:
  - term: open account
    definition: An account still in use.
    table: accounts
    sql: status = 'open'
  - term: fiscal year
    definition: Starts on the first of April.
examples:
  - question: Money on accounts per currency
    sql: SELECT currency, sum(balance) FROM accounts GROUP BY currency
  - question: Deposits per region
    sql: >-
      SELECT c.region, sum(t.amount) FROM transactions AS t
      JOIN accounts AS a ON a.id = t.account_id
      JOIN clients AS c ON c.id = a.client_id
      WHERE t.kind = 'deposit' GROUP BY c.region
"""
"""A knowledge file for the demo bank; the teller sees one term and one example."""
