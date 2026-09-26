"""The demo bank as a SQLite file, for tests that need a real database and no Docker."""

from __future__ import annotations

import os
import sqlite3
from typing import TYPE_CHECKING

import pytest

from .corpus import DEMO

if TYPE_CHECKING:
    from pathlib import Path


def build_demo_sqlite(directory: Path) -> Path:
    path = directory / "bank.db"
    connection = sqlite3.connect(path)
    connection.executescript((DEMO / "sqlite.sql").read_text(encoding="utf-8"))
    connection.close()
    return path


# Root may write any file whatever its mode, so a read-only file reads as writable.
needs_non_root = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root may write a read-only file",
)
