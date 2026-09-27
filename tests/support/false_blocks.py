"""The false-block report: legitimate queries the firewall refuses, and why.

Regenerate it after a change to the firewall or to a legitimate corpus:

    uv run python tests/support/false_blocks.py
"""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from forbql import Engine, Verdict
from support.corpus import (
    ATTACKS,
    PROFILE,
    connection_name,
    demo_firewall,
    legitimate_runs,
)
from support.spider import (
    PROFILE as ANYONE,
)
from support.spider import (
    connection,
    spider_firewall,
    spider_queries,
)

REPORT = ATTACKS / "legitimate" / "REPORT.md"
QUOTES = "strings take single quotes"
"""The hint a string written in double quotes gets."""


@dataclass
class Tally:
    corpus: str
    engine: str
    queries: int = 0
    refused: Counter[str] = field(default_factory=Counter)


def reason(verdict: Verdict) -> str:
    first = verdict.violations[0]
    if first.hint and QUOTES in first.hint:
        return f"{first.rule}: a string in double quotes"
    return str(first.rule)


def tallies() -> list[Tally]:
    firewall = demo_firewall()
    demo = {engine: Tally("demo bank", engine.value) for engine in Engine}
    for case, engine in legitimate_runs():
        verdict = firewall.check(
            case.sql,
            connection=connection_name(engine),
            profile=PROFILE,
        )
        demo[engine].queries += 1
        if not verdict.allowed:
            demo[engine].refused[reason(verdict)] += 1
    spider = Tally("Spider dev", Engine.SQLITE.value)
    for query in spider_queries():
        verdict = spider_firewall(query.db).check(
            query.sql,
            connection=connection(query.db),
            profile=ANYONE,
        )
        spider.queries += 1
        if not verdict.allowed:
            spider.refused[reason(verdict)] += 1
    return [*demo.values(), spider]


def render() -> str:
    rows: list[str] = []
    for tally in tallies():
        refused = sum(tally.refused.values())
        share = f"{100 * refused / tally.queries:.1f}%"
        why = "; ".join(f"{name} ({n})" for name, n in sorted(tally.refused.items()))
        cells = (tally.corpus, tally.engine, tally.queries, refused, share, why or "—")
        rows.append("| " + " | ".join(map(str, cells)) + " |")
    table = "\n".join(rows)
    return f"""# False blocks

Legitimate queries the firewall refuses. Every profile here may see every table and
column, so each refusal comes from the firewall's own rules, not from a policy. The
demo bank's queries are forbql's own; Spider's are what people wrote for a text-to-SQL
benchmark, over 20 SQLite databases ([attribution](spider/README.md)).

| Corpus | Engine | Queries | Refused | Share | Why |
|---|---|---|---|---|---|
{table}

SQLite reads `"text"` as a column, and as a string only when no column has that name,
so the meaning of such a query depends on the schema: the firewall refuses it and tells
the agent to use single quotes.

This file is generated: `uv run python tests/support/false_blocks.py`. A test fails
when it no longer matches what the firewall does.
"""


if __name__ == "__main__":
    _ = REPORT.write_text(render(), encoding="utf-8")
