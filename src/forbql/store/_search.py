"""The search index in the store, and the two rankings hybrid search fuses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from sqlalchemy import and_, delete, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert as upsert

from ._tables import search_documents

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from uuid import UUID

    from sqlalchemy import ColumnElement
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

_VECTOR = text("""
SELECT d.table_name
FROM forbql.search_documents AS d
     JOIN unnest(CAST(:tables AS text[]), CAST(:columns AS text[])) AS v (t, c)
     ON d.table_name = v.t AND d.column_name = v.c
WHERE d.workspace_id = :workspace AND d.connection = :connection AND d.model = :model
GROUP BY d.table_name
ORDER BY min(d.embedding <=> CAST(:query AS vector))
LIMIT :limit
""")
"""Tables by their nearest visible document; hidden ones never take part."""

_TEXT = text("""
WITH q AS (
    SELECT to_tsquery('simple', string_agg(quote_literal(lexeme), ' | ')) AS q
    FROM unnest(to_tsvector('simple', :text))
)
SELECT d.table_name
FROM forbql.search_documents AS d
     JOIN unnest(CAST(:tables AS text[]), CAST(:columns AS text[])) AS v (t, c)
     ON d.table_name = v.t AND d.column_name = v.c,
     q
WHERE d.workspace_id = :workspace AND d.connection = :connection
  AND d.body_tsv @@ q.q
GROUP BY d.table_name
ORDER BY max(ts_rank_cd(d.body_tsv, q.q)) DESC
LIMIT :limit
""")
"""Tables by their best visible word match; any word of the question may match."""


@dataclass(frozen=True, slots=True)
class IndexedDocument:
    """A search document with its vector, as the store keeps it.

    Attributes:
        table: str - `schema.table`.
        column: str - Column name; empty for the table's own document.
        body: str - The text.
        body_hash: str - Hash of the text.
        model: str - The model that made the vector.
        embedding: list[float] - The vector.

    """

    table: str
    column: str
    body: str
    body_hash: str
    model: str
    embedding: list[float]


class StoreSearch:
    """A workspace's search index: derived from snapshots, rebuilt at will.

    Args:
        engine: AsyncEngine - The store.
        workspace_id: UUID - Whose index.

    """

    _engine: AsyncEngine
    _workspace_id: UUID

    def __init__(self, engine: AsyncEngine, workspace_id: UUID) -> None:
        self._engine = engine
        self._workspace_id = workspace_id

    async def indexed(self, connection: str) -> dict[tuple[str, str], tuple[str, str]]:
        """Say what the index holds for a connection.

        Args:
            connection: str - Connection name.

        Returns:
            dict[tuple[str, str], tuple[str, str]] - `(table, column)` to the text's
                hash and the model.

        """
        query = select(
            search_documents.c.table_name,
            search_documents.c.column_name,
            search_documents.c.body_hash,
            search_documents.c.model,
        ).where(self._mine(connection))
        async with self._engine.connect() as db:
            rows = cast(
                "Sequence[tuple[str, str, str, str]]",
                (await db.execute(query)).all(),
            )
        return {(table, column): (body, model) for table, column, body, model in rows}

    async def update(
        self,
        connection: str,
        documents: Sequence[IndexedDocument],
        removed: Sequence[tuple[str, str]],
    ) -> None:
        """Write new and changed documents and drop removed ones, in one transaction.

        Args:
            connection: str - Connection name.
            documents: Sequence[IndexedDocument] - Documents to write.
            removed: Sequence[tuple[str, str]] - `(table, column)` to drop.

        """
        async with self._engine.begin() as db:
            if removed:
                keys = tuple_(
                    search_documents.c.table_name,
                    search_documents.c.column_name,
                )
                _ = await db.execute(
                    delete(search_documents).where(
                        self._mine(connection),
                        keys.in_(list(removed)),
                    ),
                )
            for document in documents:
                await self._write(db, connection, document)

    async def ranked(  # ruff: ignore[too-many-arguments] - the query and what bounds it
        self,
        connection: str,
        *,
        text_query: str,
        vector: Sequence[float],
        model: str,
        visible: Mapping[str, Sequence[str]],
        limit: int,
    ) -> tuple[list[str], list[str]]:
        """Rank tables by their visible documents, by meaning and by words.

        Args:
            connection: str - Connection name.
            text_query: str - The question.
            vector: Sequence[float] - Its embedding.
            model: str - The model that made it; other models' vectors are skipped.
            visible: Mapping[str, Sequence[str]] - Columns the profile sees per table.
            limit: int - Tables per ranking.

        Returns:
            tuple[list[str], list[str]] - Tables by meaning, then by words.

        """
        pairs = [(table, "") for table in visible] + [
            (table, column) for table, columns in visible.items() for column in columns
        ]
        common = {
            "workspace": self._workspace_id,
            "connection": connection,
            "tables": [table for table, _ in pairs],
            "columns": [column for _, column in pairs],
            "limit": limit,
        }
        query = "[" + ",".join(str(x) for x in vector) + "]"
        async with self._engine.connect() as db:
            meaning = await db.execute(
                _VECTOR,
                {**common, "query": query, "model": model},
            )
            words = await db.execute(_TEXT, {**common, "text": text_query})
            return (
                [str(row[0]) for row in meaning.all()],  # pyright: ignore[reportAny]
                [str(row[0]) for row in words.all()],  # pyright: ignore[reportAny]
            )

    async def _write(
        self,
        db: AsyncConnection,
        connection: str,
        document: IndexedDocument,
    ) -> None:
        """Insert a document, or replace the one at its place.

        Args:
            db: AsyncConnection - The open transaction.
            connection: str - Connection name.
            document: IndexedDocument - The document.

        """
        values = {
            "body": document.body,
            "body_hash": document.body_hash,
            "model": document.model,
            "embedding": document.embedding,
        }
        statement = upsert(search_documents).values(
            workspace_id=self._workspace_id,
            connection=connection,
            table_name=document.table,
            column_name=document.column,
            **values,
        )
        _ = await db.execute(
            statement.on_conflict_do_update(
                index_elements=[
                    "workspace_id",
                    "connection",
                    "table_name",
                    "column_name",
                ],
                set_=values,
            ),
        )

    def _mine(self, connection: str) -> ColumnElement[bool]:
        """Filter the index to this workspace and connection.

        Args:
            connection: str - Connection name.

        Returns:
            ColumnElement[bool] - The condition.

        """
        return and_(
            search_documents.c.workspace_id == self._workspace_id,
            search_documents.c.connection == connection,
        )
