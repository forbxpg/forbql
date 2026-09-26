"""What forbql knows about a database: snapshots of its schema and their changes."""

from __future__ import annotations

from ._diff import diff_catalogs
from ._erd import MAX_TABLES, erd

__all__ = ("MAX_TABLES", "diff_catalogs", "erd")
