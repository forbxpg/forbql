"""What forbql knows about a database: schema, diagrams, glossary, examples, search."""

from __future__ import annotations

from ._diff import diff_catalogs
from ._documents import SearchDocument, documents
from ._embed import MODEL, Embedder, FastEmbedder
from ._erd import MAX_TABLES, erd
from ._file import (
    Example,
    GlossaryTerm,
    KnowledgeError,
    KnowledgeFile,
    load_knowledge,
    parse_knowledge,
)
from ._search import LIMIT, IndexChange, SearchHit, index_catalog, search

__all__ = (
    "LIMIT",
    "MAX_TABLES",
    "MODEL",
    "Embedder",
    "Example",
    "FastEmbedder",
    "GlossaryTerm",
    "IndexChange",
    "KnowledgeError",
    "KnowledgeFile",
    "SearchDocument",
    "SearchHit",
    "diff_catalogs",
    "documents",
    "erd",
    "index_catalog",
    "load_knowledge",
    "parse_knowledge",
    "search",
)
