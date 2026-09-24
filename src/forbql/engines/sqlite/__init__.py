"""SQLite: a read-only file, query_only, and an authorizer in place of roles."""

from __future__ import annotations

from ._engine import SQLiteEngine

__all__ = ("SQLiteEngine",)
