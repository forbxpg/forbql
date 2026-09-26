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
