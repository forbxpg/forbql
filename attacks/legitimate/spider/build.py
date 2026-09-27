"""Adapt the Spider development set: its queries and its databases' tables and columns.

Spider's archive holds `dev.json` and `tables.json`; download it from
https://yale-lily.github.io/spider and pass the directory holding both. Nothing but
the SQL and the schema is kept. From the repository root:

    uv run python attacks/legitimate/spider/build.py path/to/spider_data
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

OUT = Path(__file__).parent


def main(source: Path) -> None:
    """Write `queries.yaml` and `schemas.yaml` from Spider's dev files.

    Args:
        source: Path - The directory holding `dev.json` and `tables.json`.

    """
    dev = json.loads((source / "dev.json").read_text(encoding="utf-8"))
    databases = {row["db_id"] for row in dev}
    schemas: dict[str, dict[str, list[str]]] = {}
    for table in json.loads((source / "tables.json").read_text(encoding="utf-8")):
        if table["db_id"] not in databases:
            continue
        names = table["table_names_original"]
        columns: dict[str, list[str]] = {name: [] for name in names}
        for owner, column in table["column_names_original"]:
            # Spider lists `*` first, owned by no table.
            if owner >= 0:
                columns[names[owner]].append(column)
        schemas[table["db_id"]] = columns
    # The same query is asked several ways; each counts once.
    queries = list(dict.fromkeys((row["db_id"], row["query"].strip()) for row in dev))
    _write(OUT / "schemas.yaml", dict(sorted(schemas.items())))
    _write(OUT / "queries.yaml", [{"db": db, "sql": sql} for db, sql in queries])


def _write(path: Path, data: object) -> None:
    """Write YAML the way every regeneration writes it.

    Args:
        path: Path - Where.
        data: object - What.

    """
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100)
    _ = path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
