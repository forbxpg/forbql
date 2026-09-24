"""The local stand of deploy/compose.yaml: DSNs, and the demo data it was seeded with."""

from __future__ import annotations

import runpy
from functools import cache

from forbql import Engine

from .corpus import DEMO

# Ports and passwords of deploy/compose.yaml.
READER = {
    Engine.POSTGRES: "postgresql://forbql_reader:forbql_reader@127.0.0.1:55433/bank",
    Engine.MYSQL: "mysql://forbql_reader:forbql_reader@127.0.0.1:53306/bank",
}
ADMIN = {
    Engine.POSTGRES: "postgresql://postgres:demo-local-only@127.0.0.1:55433/bank",
    Engine.MYSQL: "mysql://root:demo-local-only@127.0.0.1:53306/bank",
}


@cache
def seeded_names() -> tuple[tuple[object, ...], ...]:
    """Every client's id and full name, as the seed generator wrote them.

    Returns:
        tuple[tuple[object, ...], ...] - `(id, full_name)` in id order.

    """
    tables = runpy.run_path(str(DEMO / "generate.py"))["build"]()
    clients = next(table for table in tables if table.name == "clients")
    return tuple((row[0], row[1]) for row in clients.rows)
