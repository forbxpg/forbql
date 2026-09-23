from __future__ import annotations

import runpy
import sqlite3
from pathlib import Path

DEMO = Path(__file__).parents[2] / "deploy" / "demo"


def test_committed_seeds_match_the_generator():
    rendered: dict[str, str] = runpy.run_path(str(DEMO / "generate.py"))["render"]()

    for name, content in rendered.items():
        assert (DEMO / name).read_text(encoding="utf-8") == content, (
            f"run deploy/demo/generate.py: {name} is stale"
        )


def test_sqlite_seed_builds_the_demo_bank():
    connection = sqlite3.connect(":memory:")
    connection.executescript((DEMO / "sqlite.sql").read_text(encoding="utf-8"))

    def scalar(sql: str) -> object:
        return connection.execute(sql).fetchone()[0]

    assert scalar("SELECT count(*) FROM clients") == 201
    assert (
        scalar(
            "SELECT count(*) FROM accounts WHERE client_id NOT IN (SELECT id FROM clients)",
        )
        == 0
    )
    assert scalar("SELECT value FROM canary") == "untouched"
    assert scalar("SELECT count(*) FROM clients WHERE full_name = 'Sean O''Brien'") == 1
    assert "Ignore all previous instructions" in str(
        scalar("SELECT description FROM transactions WHERE id = 1"),
    )
