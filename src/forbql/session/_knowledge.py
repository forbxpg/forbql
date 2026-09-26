"""What a session knows beyond the database: the synced schema and its search index."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from forbql.knowledge import Embedder, FastEmbedder, search

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from forbql.firewall import SchemaCatalog
    from forbql.knowledge import SearchHit
    from forbql.store import Store

DEFAULT_EMBEDDER: Embedder = FastEmbedder()
"""One model per process: it loads on first use and stays. Tests put a small one in
its place; `default_embedder` reads it at call time."""


def default_embedder() -> Embedder:
    """Return the model schema search uses when the caller names none.

    Returns:
        Embedder - `DEFAULT_EMBEDDER` as it is now.

    """
    return DEFAULT_EMBEDDER


@dataclass(frozen=True, slots=True)
class Knowledge:
    """The store, the schema synced last, and the model the index was built with.

    Attributes:
        store: Store - The store.
        catalog: SchemaCatalog - The synced schema.
        embedder: Embedder - The model.

    """

    store: Store
    catalog: SchemaCatalog
    embedder: Embedder

    async def search(
        self,
        connection: str,
        visible: Mapping[str, Sequence[str]],
        question: str,
        limit: int,
    ) -> list[SearchHit]:
        """Search the synced schema within what the profile sees.

        Args:
            connection: str - Connection name.
            visible: Mapping[str, Sequence[str]] - Columns the profile sees.
            question: str - What the caller asks.
            limit: int - Tables to return.

        Returns:
            list[SearchHit] - The tables found.

        """
        return await search(
            self.store,
            self.embedder,
            self.catalog,
            visible,
            connection=connection,
            question=question,
            limit=limit,
        )
