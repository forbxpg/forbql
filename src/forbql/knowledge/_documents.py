"""What schema search reads: one document per table and one per column."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from forbql.firewall import SchemaCatalog

TABLE = ""
"""The `column` of a table's own document."""


@dataclass(frozen=True, slots=True)
class SearchDocument:
    """One thing search can find.

    A column is a document of its own, so a column the profile cannot see is dropped
    before ranking and never pulls its table up.

    Attributes:
        table: str - `schema.table`.
        column: str - Column name; empty for the table's own document.
        body: str - The text to match: names in words, and comments.

    """

    table: str
    column: str
    body: str

    @property
    def body_hash(self) -> str:
        """Hash of the text, to re-embed only what changed.

        Returns:
            str - Hex SHA-256.

        """
        return hashlib.sha256(self.body.encode()).hexdigest()


def documents(catalog: SchemaCatalog) -> list[SearchDocument]:
    """Turn a catalog into documents, in table order.

    Args:
        catalog: SchemaCatalog - The synced schema.

    Returns:
        list[SearchDocument] - A table's document, then its columns'.

    """
    found: list[SearchDocument] = []
    for name, info in catalog.tables.items():
        table = _words(name.split(".", 1)[1])
        about = f"{table}: {info.comment}" if info.comment else table
        found.append(SearchDocument(table=name, column=TABLE, body=about))
        found.extend(
            SearchDocument(
                table=name,
                column=column.name,
                body=f"{table} {_words(column.name)}"
                + (f" ({column.comment})" if column.comment else ""),
            )
            for column in info.columns
        )
    return found


def _words(name: str) -> str:
    """Write an identifier as words: `loan_payments` becomes `loan payments`.

    Args:
        name: str - The identifier.

    Returns:
        str - The words.

    """
    return re.sub(r"[_.]+", " ", name).strip()
