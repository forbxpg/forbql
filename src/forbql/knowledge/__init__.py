"""What forbql knows about a database: snapshots of its schema and their changes."""

from __future__ import annotations

from ._diff import diff_catalogs

__all__ = ("diff_catalogs",)
