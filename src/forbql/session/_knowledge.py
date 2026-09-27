"""What a session knows beyond the database: the synced schema, glossary, examples."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from forbql.knowledge import (
    Embedder,
    FastEmbedder,
    allowed,
    search_everything,
    stored_entries,
)

if TYPE_CHECKING:
    from forbql.firewall import Firewall, SchemaCatalog
    from forbql.knowledge import GlossaryTerm, SearchResult
    from forbql.policy import Engine
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
        engine: Engine - The connection's engine, whose dialect terms are written in.

    """

    store: Store
    catalog: SchemaCatalog
    embedder: Embedder
    engine: Engine

    async def search(
        self,
        firewall: Firewall,
        *,
        connection: str,
        profile: str,
        question: str,
        limit: int,
    ) -> SearchResult:
        """Search the synced schema, glossary and examples within what a profile sees.

        Every term and example is checked under the profile first; the rest never
        reaches the ranking.

        Args:
            firewall: Firewall - The session's firewall.
            connection: str - Connection name.
            profile: str - Who asks.
            question: str - What the caller asks.
            limit: int - Tables to return.

        Returns:
            SearchResult - Tables, terms and examples.

        """
        terms, examples = await stored_entries(self.store, connection)
        return await search_everything(
            self.store,
            self.embedder,
            self.catalog,
            firewall.visible(connection, profile),
            terms=allowed(
                terms,
                firewall=firewall,
                connection=connection,
                profile=profile,
                catalog=self.catalog,
                engine=self.engine,
            ),
            examples=allowed(
                examples,
                firewall=firewall,
                connection=connection,
                profile=profile,
                catalog=self.catalog,
                engine=self.engine,
            ),
            connection=connection,
            question=question,
            limit=limit,
        )

    async def glossary(
        self,
        firewall: Firewall,
        *,
        connection: str,
        profile: str,
    ) -> list[GlossaryTerm]:
        """Read the glossary terms a profile may see.

        Args:
            firewall: Firewall - The session's firewall.
            connection: str - Connection name.
            profile: str - Who asks.

        Returns:
            list[GlossaryTerm] - The terms, by term.

        """
        terms, _ = await stored_entries(self.store, connection)
        return allowed(
            terms,
            firewall=firewall,
            connection=connection,
            profile=profile,
            catalog=self.catalog,
            engine=self.engine,
        )
