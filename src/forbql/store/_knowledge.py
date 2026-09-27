"""Glossary terms and examples in the store, and their rankings for search."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from itertools import starmap
from typing import TYPE_CHECKING, cast

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Float,
    Table,
    Text,
    and_,
    delete,
    func,
    literal,
    literal_column,
    select,
)
from sqlalchemy.dialects.postgresql import insert as upsert
from sqlalchemy.exc import IntegrityError

from ._errors import StoreError
from ._tables import examples, glossary_terms

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from uuid import UUID

    from sqlalchemy import ColumnElement
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


class KnowledgeKind(StrEnum):
    """What a knowledge entry is."""

    GLOSSARY = "glossary"
    EXAMPLES = "examples"


_TABLES: dict[KnowledgeKind, tuple[Table, str]] = {
    KnowledgeKind.GLOSSARY: (glossary_terms, "term"),
    KnowledgeKind.EXAMPLES: (examples, "question"),
}
"""Each kind's table and the column naming an entry."""

_SIMPLE = literal_column("'simple'::regconfig", Text())
"""The text search configuration: no stemming, so identifiers and any language match."""


@dataclass(frozen=True, slots=True)
class StoredTerm:
    """A glossary term as the store keeps it, without its vector.

    Attributes:
        term: str - The word.
        definition: str - What it means.
        table: str | None - `schema.table` its expression reads.
        sql: str | None - The expression.
        body_hash: str - Hash of the entry.
        model: str - The model that made its vector.

    """

    term: str
    definition: str
    table: str | None
    sql: str | None
    body_hash: str
    model: str


@dataclass(frozen=True, slots=True)
class StoredExample:
    """An example as the store keeps it, without its vector.

    Attributes:
        question: str - The question.
        sql: str - The query.
        body_hash: str - Hash of the entry.
        model: str - The model that made its vector.

    """

    question: str
    sql: str
    body_hash: str
    model: str


class StoreKnowledge:
    """A workspace's glossary and examples: what the last knowledge sync loaded.

    Args:
        engine: AsyncEngine - The store.
        workspace_id: UUID - Whose knowledge.

    """

    _engine: AsyncEngine
    _workspace_id: UUID

    def __init__(self, engine: AsyncEngine, workspace_id: UUID) -> None:
        self._engine = engine
        self._workspace_id = workspace_id

    async def terms(self, connection: str) -> list[StoredTerm]:
        """Read a connection's glossary.

        Args:
            connection: str - Connection name.

        Returns:
            list[StoredTerm] - Its terms, by term.

        """
        t = glossary_terms.c
        query = (
            select(t.term, t.definition, t.table_name, t.sql, t.body_hash, t.model)
            .where(self._mine(glossary_terms, connection))
            .order_by(t.term)
        )
        async with self._engine.connect() as db:
            rows = cast(
                "Sequence[tuple[str, str, str | None, str | None, str, str]]",
                (await db.execute(query)).all(),
            )
        return list(starmap(StoredTerm, rows))

    async def examples(self, connection: str) -> list[StoredExample]:
        """Read a connection's examples.

        Args:
            connection: str - Connection name.

        Returns:
            list[StoredExample] - Its examples, by question.

        """
        e = examples.c
        query = (
            select(e.question, e.sql, e.body_hash, e.model)
            .where(self._mine(examples, connection))
            .order_by(e.question)
        )
        async with self._engine.connect() as db:
            rows = cast(
                "Sequence[tuple[str, str, str, str]]",
                (await db.execute(query)).all(),
            )
        return list(starmap(StoredExample, rows))

    async def update(
        self,
        connection: str,
        *,
        terms: Sequence[tuple[StoredTerm, Sequence[float]]] = (),
        examples: Sequence[tuple[StoredExample, Sequence[float]]] = (),
        removed_terms: Sequence[str] = (),
        removed_examples: Sequence[str] = (),
    ) -> None:
        """Write new and changed entries and drop removed ones, in one transaction.

        Args:
            connection: str - Connection name.
            terms: Sequence[tuple[StoredTerm, Sequence[float]]] - Terms and vectors.
            examples: Sequence[tuple[StoredExample, Sequence[float]]] - Examples and
                vectors.
            removed_terms: Sequence[str] - Terms to drop.
            removed_examples: Sequence[str] - Questions to drop.

        Raises:
            StoreError: If the store refuses an entry; nothing is changed then.

        """
        writes = [
            (KnowledgeKind.GLOSSARY, _term_values(term), vector)
            for term, vector in terms
        ] + [
            (KnowledgeKind.EXAMPLES, _example_values(example), vector)
            for example, vector in examples
        ]
        try:
            async with self._engine.begin() as db:
                for kind, removed in (
                    (KnowledgeKind.GLOSSARY, removed_terms),
                    (KnowledgeKind.EXAMPLES, removed_examples),
                ):
                    table, key = _TABLES[kind]
                    if removed:
                        _ = await db.execute(
                            delete(table).where(
                                self._mine(table, connection),
                                table.c[key].in_(list(removed)),
                            ),
                        )
                for kind, values, vector in writes:
                    await self._write(db, connection, kind, values, vector)
        except IntegrityError as error:
            msg = f"the store refused the knowledge of {connection}: {error.orig}"
            raise StoreError(msg) from error

    async def ranked(  # ruff: ignore[too-many-arguments] - the query and what bounds it
        self,
        connection: str,
        kind: KnowledgeKind,
        *,
        text_query: str,
        vector: Sequence[float],
        model: str,
        allowed: Sequence[str],
        limit: int,
    ) -> tuple[list[str], list[str]]:
        """Rank the entries a profile may see, by meaning and by words.

        Args:
            connection: str - Connection name.
            kind: KnowledgeKind - Terms or examples.
            text_query: str - The question.
            vector: Sequence[float] - Its embedding.
            model: str - The model that made it; other models' vectors are skipped.
            allowed: Sequence[str] - Terms or questions the profile may see.
            limit: int - Entries per ranking.

        Returns:
            tuple[list[str], list[str]] - Entries by meaning, then by words.

        """
        table, key = _TABLES[kind]
        name = table.c[key]
        mine = and_(self._mine(table, connection), name.in_(list(allowed)))
        meaning = (
            select(name)
            .where(mine, table.c.model == model)
            .order_by(
                table.c.embedding.op("<=>", return_type=Float())(
                    literal(list(vector), Vector()),
                ),
            )
            .limit(limit)
        )
        # Any word of the question may match: its lexemes joined by OR.
        lexemes = func.unnest(
            func.to_tsvector(_SIMPLE, text_query),
        ).table_valued("lexeme")
        words_query = (
            select(
                func.to_tsquery(
                    _SIMPLE,
                    func.string_agg(func.quote_literal(lexemes.c.lexeme), " | "),
                ),
            )
            .select_from(lexemes)
            .scalar_subquery()
        )
        words = (
            select(name)
            .where(mine, table.c.body_tsv.op("@@")(words_query))
            .order_by(func.ts_rank_cd(table.c.body_tsv, words_query).desc())
            .limit(limit)
        )
        async with self._engine.connect() as db:
            by_meaning = cast(
                "Sequence[str]",
                (await db.execute(meaning)).scalars().all(),
            )
            by_words = cast("Sequence[str]", (await db.execute(words)).scalars().all())
        return list(by_meaning), list(by_words)

    async def _write(
        self,
        db: AsyncConnection,
        connection: str,
        kind: KnowledgeKind,
        values: Mapping[str, str | None],
        vector: Sequence[float],
    ) -> None:
        """Insert an entry, or replace the one of the same name.

        Args:
            db: AsyncConnection - The open transaction.
            connection: str - Connection name.
            kind: KnowledgeKind - Terms or examples.
            values: Mapping[str, str | None] - The entry's columns.
            vector: Sequence[float] - Its embedding.

        """
        table, key = _TABLES[kind]
        row = {**values, "embedding": list(vector)}
        statement = upsert(table).values(
            workspace_id=self._workspace_id,
            connection=connection,
            **row,
        )
        _ = await db.execute(
            statement.on_conflict_do_update(
                index_elements=["workspace_id", "connection", key],
                set_=row,
            ),
        )

    def _mine(self, table: Table, connection: str) -> ColumnElement[bool]:
        """Filter a table to this workspace and connection.

        Args:
            table: Table - Terms or examples.
            connection: str - Connection name.

        Returns:
            ColumnElement[bool] - The condition.

        """
        return and_(
            table.c.workspace_id == self._workspace_id,
            table.c.connection == connection,
        )


def _term_values(term: StoredTerm) -> dict[str, str | None]:
    """Name a term's columns.

    Args:
        term: StoredTerm - The term.

    Returns:
        dict[str, str | None] - Column values.

    """
    return {
        "term": term.term,
        "definition": term.definition,
        "table_name": term.table,
        "sql": term.sql,
        "body_hash": term.body_hash,
        "model": term.model,
    }


def _example_values(example: StoredExample) -> dict[str, str | None]:
    """Name an example's columns.

    Args:
        example: StoredExample - The example.

    Returns:
        dict[str, str | None] - Column values.

    """
    return {
        "question": example.question,
        "sql": example.sql,
        "body_hash": example.body_hash,
        "model": example.model,
    }
