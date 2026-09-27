# False blocks

Legitimate queries the firewall refuses. Every profile here may see every table and
column, so each refusal comes from the firewall's own rules, not from a policy. The
demo bank's queries are forbql's own; Spider's are what people wrote for a text-to-SQL
benchmark, over 20 SQLite databases ([attribution](spider/README.md)).

| Corpus | Engine | Queries | Refused | Share | Why |
|---|---|---|---|---|---|
| demo bank | postgres | 27 | 0 | 0.0% | — |
| demo bank | mysql | 27 | 0 | 0.0% | — |
| demo bank | sqlite | 26 | 0 | 0.0% | — |
| Spider dev | sqlite | 564 | 112 | 19.9% | unknown_column: a string in double quotes (112) |

SQLite reads `"text"` as a column, and as a string only when no column has that name,
so the meaning of such a query depends on the schema: the firewall refuses it and tells
the agent to use single quotes.

This file is generated: `uv run python tests/support/false_blocks.py`. A test fails
when it no longer matches what the firewall does.
