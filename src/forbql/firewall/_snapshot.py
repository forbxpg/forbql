"""The database schema the firewall checks queries against."""

from __future__ import annotations

from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SchemaSnapshot(BaseModel):
    """Tables and columns of one database at one moment.

    The firewall does no I/O, so the caller supplies this; introspection produces it.

    Attributes:
        default_schema: str - Schema unqualified tables resolve to: the head of the
            PostgreSQL search path, the MySQL database, `main` for SQLite.
        tables: dict[str, tuple[str, ...]] - Columns of every table and view as
            `schema.table`, including tables no profile may see.
        views: dict[str, str | None] - Definition of every view in `tables`; None
            when the role may not read it.

    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    default_schema: str
    tables: dict[str, tuple[str, ...]]
    views: dict[str, str | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_names(self) -> Self:
        """Require every table to be written as `schema.table`, every view in `tables`.

        Returns:
            Self - The validated snapshot.

        Raises:
            ValueError: If a table name is not `schema.table`, or a view has no columns.

        """
        bad = sorted(name for name in self.tables if name.count(".") != 1)
        if bad:
            msg = f"tables must be named 'schema.table': {', '.join(bad)}"
            raise ValueError(msg)
        if missing := sorted(self.views.keys() - self.tables.keys()):
            msg = f"views missing from tables: {', '.join(missing)}"
            raise ValueError(msg)
        return self
