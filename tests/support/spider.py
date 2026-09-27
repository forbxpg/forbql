"""The Spider development set, adapted: its queries and a firewall per database."""

from __future__ import annotations

from functools import cache
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, TypeAdapter

from forbql import Firewall, SchemaSnapshot
from forbql.policy import parse_policy
from support.corpus import ATTACKS, load_yaml

SPIDER = ATTACKS / "legitimate" / "spider"
PROFILE = "anyone"


class SpiderQuery(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    db: str
    sql: str


_QUERIES = TypeAdapter(tuple[SpiderQuery, ...])
_SCHEMAS = TypeAdapter(dict[str, dict[str, tuple[str, ...]]])

_POLICY = """version: 1
connections:
  {connection}:
    engine: sqlite
    profiles:
      {profile}:
        tables:
{tables}
"""


@cache
def spider_queries() -> tuple[SpiderQuery, ...]:
    text = (SPIDER / "queries.yaml").read_text(encoding="utf-8")
    return _QUERIES.validate_python(load_yaml(text))


@cache
def spider_schemas() -> dict[str, dict[str, tuple[str, ...]]]:
    text = (SPIDER / "schemas.yaml").read_text(encoding="utf-8")
    return _SCHEMAS.validate_python(load_yaml(text))


def connection(db: str) -> str:
    # Policy connection names are lower case; Spider's database names are not all.
    return db.lower()


@cache
def spider_firewall(db: str) -> Firewall:
    """A firewall over one Spider database that lets its profile see everything.

    Whatever it refuses is refused by the firewall's own rules, not by the policy.

    Returns:
        Firewall - The firewall, with a SQLite snapshot of the database.

    """
    tables = spider_schemas()[db]
    listed = "\n".join(
        f'          "main.{name}": {{ columns: "*" }}' for name in tables
    )
    policy = parse_policy(
        _POLICY.format(connection=connection(db), profile=PROFILE, tables=listed),
    )
    snapshot = SchemaSnapshot(
        default_schema="main",
        tables={f"main.{name}": columns for name, columns in tables.items()},
    )
    return Firewall(policy, {connection(db): snapshot})
