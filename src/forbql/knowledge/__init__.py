"""What forbql knows about a database: schema, diagrams, glossary, examples, search."""

from __future__ import annotations

from ._describe import (
    SAMPLE_FLOOR,
    ColumnDescription,
    TableDescription,
    describe,
    sample_query,
)
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
from ._search import (
    KNOWLEDGE_LIMIT,
    LIMIT,
    IndexChange,
    SearchHit,
    SearchResult,
    index_catalog,
    search,
    search_everything,
)
from ._sync import (
    KnowledgeChange,
    Reach,
    index_knowledge,
    reach,
    resolved,
    stored_entries,
    unseen,
)
from ._visibility import (
    allowed,
    glossary_query,
    hidden_names,
    mentions,
    resolve_table,
    why_hidden,
)

__all__ = (
    "KNOWLEDGE_LIMIT",
    "LIMIT",
    "MAX_TABLES",
    "MODEL",
    "SAMPLE_FLOOR",
    "ColumnDescription",
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
    "SearchResult",
    "TableDescription",
    "allowed",
    "describe",
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
    "sample_query",
    "search",
    "search_everything",
    "stored_entries",
    "unseen",
    "why_hidden",
)
