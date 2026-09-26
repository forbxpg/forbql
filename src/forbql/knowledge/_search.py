"""Hybrid schema search: meaning and words fused, then joined tables brought along."""

from __future__ import annotations

from asyncio import to_thread
from dataclasses import dataclass
from operator import itemgetter
from typing import TYPE_CHECKING

from forbql.store import IndexedDocument

from ._documents import documents

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from forbql.firewall import SchemaCatalog
    from forbql.store import Store

    from ._embed import Embedder

LIMIT = 8
"""Tables a search returns."""

_TOP = 3
"""Best matches whose joined tables come along."""

_RANKED = 20
"""Tables each ranking offers the fusion."""

_RRF = 60
"""The constant of reciprocal rank fusion: ranks weigh 1 / (60 + rank)."""


@dataclass(frozen=True, slots=True)
class SearchHit:
    """A table search found.

    Attributes:
        table: str - `schema.table`.
        columns: tuple[str, ...] - Its columns the profile sees.
        joined_from: str | None - The matched table it joins; None for a match.

    """

    table: str
    columns: tuple[str, ...]
    joined_from: str | None = None


@dataclass(frozen=True, slots=True)
class IndexChange:
    """What indexing did.

    Attributes:
        embedded: int - Documents embedded now: new or changed.
        removed: int - Documents dropped with their tables or columns.

    """

    embedded: int
    removed: int


async def index_catalog(
    store: Store,
    embedder: Embedder,
    connection: str,
    catalog: SchemaCatalog,
    *,
    everything: bool = False,
) -> IndexChange:
    """Bring a connection's search index in line with its synced schema.

    Only documents whose text or model changed are embedded again.

    Args:
        store: Store - The store.
        embedder: Embedder - The model.
        connection: str - Connection name.
        catalog: SchemaCatalog - The synced schema.
        everything: bool - Embed every document again.

    Returns:
        IndexChange - What was embedded and removed.

    """
    wanted = documents(catalog)
    held = await store.search.indexed(connection)
    fresh = [
        document
        for document in wanted
        if everything
        or held.get((document.table, document.column))
        != (document.body_hash, embedder.name)
    ]
    removed = sorted(held.keys() - {(d.table, d.column) for d in wanted})
    # Nothing to embed, nothing to load: the model takes seconds to start.
    vectors = (
        await to_thread(embedder.documents, [d.body for d in fresh]) if fresh else []
    )
    await store.search.update(
        connection,
        [
            IndexedDocument(
                table=document.table,
                column=document.column,
                body=document.body,
                body_hash=document.body_hash,
                model=embedder.name,
                embedding=vector,
            )
            for document, vector in zip(fresh, vectors, strict=True)
        ],
        removed,
    )
    return IndexChange(embedded=len(fresh), removed=len(removed))


async def search(  # ruff: ignore[too-many-arguments] - the question and what bounds it
    store: Store,
    embedder: Embedder,
    catalog: SchemaCatalog,
    visible: Mapping[str, Sequence[str]],
    *,
    connection: str,
    question: str,
    limit: int = LIMIT,
) -> list[SearchHit]:
    """Find the tables a question needs, among those the profile sees.

    Args:
        store: Store - The store.
        embedder: Embedder - The model the index was built with.
        catalog: SchemaCatalog - The synced schema, for joins.
        visible: Mapping[str, Sequence[str]] - Columns the profile sees per table.
        connection: str - Connection name.
        question: str - What the caller asks, in any language.
        limit: int - Tables to return.

    Returns:
        list[SearchHit] - Matches, each followed by the tables it joins.

    """
    vector = await to_thread(embedder.query, question)
    rankings = await store.search.ranked(
        connection,
        text_query=question,
        vector=vector,
        model=embedder.name,
        visible=visible,
        limit=_RANKED,
    )
    scores = fuse(rankings)
    return [
        SearchHit(table=table, columns=tuple(visible[table]), joined_from=source)
        for table, source in expand(scores, neighbours(catalog, visible), limit)
    ]


def fuse(rankings: Sequence[Sequence[str]]) -> dict[str, float]:
    """Fuse rankings by reciprocal rank: a table high in either rises.

    Args:
        rankings: Sequence[Sequence[str]] - Tables, best first, per ranking.

    Returns:
        dict[str, float] - Score per table, highest first.

    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, table in enumerate(ranking, start=1):
            scores[table] = scores.get(table, 0.0) + 1 / (_RRF + rank)
    return dict(sorted(scores.items(), key=itemgetter(1), reverse=True))


def neighbours(
    catalog: SchemaCatalog,
    visible: Mapping[str, Sequence[str]],
) -> dict[str, set[str]]:
    """Join visible tables by foreign keys whose columns are all visible.

    Args:
        catalog: SchemaCatalog - The schema.
        visible: Mapping[str, Sequence[str]] - Columns the profile sees per table.

    Returns:
        dict[str, set[str]] - Tables each visible table joins, both ways.

    """
    joined: dict[str, set[str]] = {table: set() for table in visible}
    for table in visible:
        info = catalog.tables.get(table)
        for key in info.foreign_keys if info else ():
            if (
                key.table in visible
                and set(key.columns) <= set(visible[table])
                and set(key.references) <= set(visible[key.table])
            ):
                joined[table].add(key.table)
                joined[key.table].add(table)
    return joined


def expand(
    scores: Mapping[str, float],
    joined: Mapping[str, set[str]],
    limit: int,
) -> list[tuple[str, str | None]]:
    """Follow the best matches with the tables they join, best joined first.

    Args:
        scores: Mapping[str, float] - Fused scores, highest first.
        joined: Mapping[str, set[str]] - Joins between visible tables.
        limit: int - Tables to return.

    Returns:
        list[tuple[str, str | None]] - Tables with the match they join; None for a
            match itself.

    """
    found: dict[str, str | None] = {}
    for table in list(scores)[:_TOP]:
        _ = found.setdefault(table, None)
        for other in sorted(joined.get(table, ()), key=lambda t: -scores.get(t, 0.0)):
            _ = found.setdefault(other, table)
    for table in scores:
        _ = found.setdefault(table, None)
    return list(found.items())[:limit]
