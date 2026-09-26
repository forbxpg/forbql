"""What forbql knows about a database: its schema, changes, diagrams and search."""

from __future__ import annotations

from ._diff import diff_catalogs
from ._documents import SearchDocument, documents
from ._embed import MODEL, Embedder, FastEmbedder
from ._erd import MAX_TABLES, erd
from ._search import LIMIT, IndexChange, SearchHit, index_catalog, search

__all__ = (
    "LIMIT",
    "MAX_TABLES",
    "MODEL",
    "Embedder",
    "FastEmbedder",
    "IndexChange",
    "SearchDocument",
    "SearchHit",
    "diff_catalogs",
    "documents",
    "erd",
    "index_catalog",
    "search",
)
