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
from ._sync import (
    KnowledgeChange,
    Reach,
    index_knowledge,
    reach,
    resolved,
    stored_entries,
)
from ._visibility import (
    glossary_query,
    hidden_names,
    mentions,
    resolve_table,
    why_hidden,
)

__all__ = (
    "LIMIT",
    "MAX_TABLES",
    "MODEL",
    "Embedder",
    "Example",
    "FastEmbedder",
    "GlossaryTerm",
    "IndexChange",
    "KnowledgeChange",
    "KnowledgeError",
    "KnowledgeFile",
    "Reach",
    "SearchDocument",
    "SearchHit",
    "diff_catalogs",
    "documents",
    "erd",
    "glossary_query",
    "hidden_names",
    "index_catalog",
    "index_knowledge",
    "load_knowledge",
    "mentions",
    "parse_knowledge",
    "reach",
    "resolve_table",
    "resolved",
    "search",
    "stored_entries",
    "why_hidden",
)
