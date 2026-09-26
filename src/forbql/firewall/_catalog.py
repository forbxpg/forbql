"""The whole schema of a database: what snapshots keep and knowledge describes."""

from __future__ import annotations

import hashlib
import json
from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict, model_validator

from ._snapshot import SchemaSnapshot


class _Frozen(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


class ColumnInfo(_Frozen):
    """One column.

    Attributes:
        name: str - Column name.
        type: str - Type as the engine names it.
        nullable: bool - Whether it may hold NULL.
        comment: str | None - The database's comment on it.

    """

    name: str
    type: str
    nullable: bool
    comment: str | None = None


class ForeignKey(_Frozen):
    """A reference from some columns of one table to another table.

    Attributes:
        columns: tuple[str, ...] - Columns of the referencing table.
        table: str - The referenced table, `schema.table`.
        references: tuple[str, ...] - Its columns, in the same order.

    """

    columns: tuple[str, ...]
    table: str
    references: tuple[str, ...]


class TableInfo(_Frozen):
    """One table or view.

    Attributes:
        columns: tuple[ColumnInfo, ...] - In the table's order.
        primary_key: tuple[str, ...] - Primary key columns; empty for none.
        foreign_keys: tuple[ForeignKey, ...] - References to other tables.
        comment: str | None - The database's comment on it.
        view: bool - Whether it is a view.
        definition: str | None - A view's query; None for tables and unreadable ones.

    """

    columns: tuple[ColumnInfo, ...]
    primary_key: tuple[str, ...] = ()
    foreign_keys: tuple[ForeignKey, ...] = ()
    comment: str | None = None
    view: bool = False
    definition: str | None = None


class SchemaCatalog(_Frozen):
    """Every table the role can see, with types, keys and comments.

    Attributes:
        default_schema: str - Schema unqualified tables resolve to.
        tables: dict[str, TableInfo] - By `schema.table`.

    """

    default_schema: str
    tables: dict[str, TableInfo]

    @model_validator(mode="after")
    def _check_references(self) -> Self:
        """Require keys to name columns that exist, in tables that exist.

        Returns:
            Self - The validated catalog.

        Raises:
            ValueError: If a key names a missing table or column.

        """
        for name, table in self.tables.items():
            own = {column.name for column in table.columns}
            if missing := sorted(set(table.primary_key) - own):
                msg = f"{name}: primary key names missing columns {missing}"
                raise ValueError(msg)
            for key in table.foreign_keys:
                target = self.tables.get(key.table)
                columns = target.columns if target else ()
                theirs = {column.name for column in columns}
                if set(key.columns) - own or set(key.references) - theirs:
                    msg = f"{name}: foreign key to {key.table} names missing columns"
                    raise ValueError(msg)
        return self

    def snapshot(self) -> SchemaSnapshot:
        """Keep what the firewall needs: names and view definitions.

        Returns:
            SchemaSnapshot - The snapshot.

        """
        return SchemaSnapshot(
            default_schema=self.default_schema,
            tables={
                name: tuple(column.name for column in table.columns)
                for name, table in self.tables.items()
            },
            views={
                name: table.definition
                for name, table in self.tables.items()
                if table.view
            },
        )

    def content_hash(self) -> str:
        """Hash the catalog, so an unchanged schema is recognised as one.

        Returns:
            str - Hex SHA-256 of canonical JSON.

        """
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()
