"""The database schema the firewall checks queries against."""

from __future__ import annotations

from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict, model_validator


class SchemaSnapshot(BaseModel):
    """Tables and columns of one database at one moment.

    The firewall does no I/O, so the caller supplies this; introspection produces it.

    Attributes:
        default_schema: str - Schema unqualified tables resolve to: the head of the
            PostgreSQL search path, the MySQL database, `main` for SQLite.
        tables: dict[str, tuple[str, ...]] - Columns of every table as `schema.table`,
            including tables no profile may see.

    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    default_schema: str
    tables: dict[str, tuple[str, ...]]

    @model_validator(mode="after")
    def _check_names(self) -> Self:
        """Require every table to be written as `schema.table`.

        Returns:
            Self - The validated snapshot.

        Raises:
            ValueError: If a table name is not `schema.table`.

        """
        bad = sorted(name for name in self.tables if name.count(".") != 1)
        if bad:
            msg = f"tables must be named 'schema.table': {', '.join(bad)}"
            raise ValueError(msg)
        return self
