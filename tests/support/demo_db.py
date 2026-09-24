"""The demo bank as a SQLite file, for tests that need a real database and no Docker."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from .corpus import DEMO

if TYPE_CHECKING:
    from pathlib import Path


def build_demo_sqlite(directory: Path) -> Path:
    path = directory / "bank.db"
    connection = sqlite3.connect(path)
    connection.executescript((DEMO / "sqlite.sql").read_text(encoding="utf-8"))
    connection.close()
    return path
