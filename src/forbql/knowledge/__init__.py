"""What forbql knows about a database: its schema, changes, diagrams and search."""

from __future__ import annotations

from ._diff import diff_catalogs
from ._documents import SearchDocument, documents
from ._embed import MODEL, Embedder, FastEmbedder
from ._erd import MAX_TABLES, erd

__all__ = (
    "MAX_TABLES",
    "MODEL",
    "Embedder",
    "FastEmbedder",
    "SearchDocument",
    "diff_catalogs",
    "documents",
    "erd",
)
