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
        generated: dict[str, dict[str, str | None]] - Generation expression of each
            generated column, by `schema.table` then column name. None means the
            column is generated and the expression cannot be read. A column absent
            here is stored.

    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    default_schema: str
    tables: dict[str, tuple[str, ...]]
    views: dict[str, str | None] = Field(default_factory=dict)
    generated: dict[str, dict[str, str | None]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_names(self) -> Self:
        """Require every table to be written as `schema.table`, every view in `tables`.

        Returns:
            Self - The validated snapshot.

        Raises:
            ValueError: If a table name is not `schema.table`, a view has no columns,
                or a generated column is not on its table.

        """
        bad = sorted(name for name in self.tables if name.count(".") != 1)
        if bad:
            msg = f"tables must be named 'schema.table': {', '.join(bad)}"
            raise ValueError(msg)
        if missing := sorted(self.views.keys() - self.tables.keys()):
            msg = f"views missing from tables: {', '.join(missing)}"
            raise ValueError(msg)
        unknown = sorted(set(self.generated) - set(self.tables))
        if unknown:
            msg = f"generated columns for unknown tables: {', '.join(unknown)}"
            raise ValueError(msg)
        for name, columns in self.generated.items():
            absent = sorted(set(columns) - set(self.tables[name]))
            if absent:
                msg = (
                    f"{name}: generated columns missing from the table: "
                    f"{', '.join(absent)}"
                )
                raise ValueError(msg)
        return self

    def within(self, reviewed: SchemaSnapshot) -> SchemaSnapshot:
        """Keep what a reviewed snapshot also has; view definitions stay current.

        Args:
            reviewed: SchemaSnapshot - The snapshot the operator synced last.

        Returns:
            SchemaSnapshot - Tables and columns in both; a table left without columns,
                or that was a view when reviewed and is a table now or the other way
                round, is left out.

        """
        tables = {
            name: kept
            for name, columns in self.tables.items()
            if (name in self.views) == (name in reviewed.views)
            and (
                kept := tuple(c for c in columns if c in reviewed.tables.get(name, ()))
            )
        }
        return SchemaSnapshot(
            default_schema=self.default_schema,
            tables=tables,
            views={name: sql for name, sql in self.views.items() if name in tables},
            generated={
                name: kept_expressions
                for name, expressions in self.generated.items()
                if name in tables
                and (
                    kept_expressions := {
                        column: expression
                        for column, expression in expressions.items()
                        if column in tables[name]
                    }
                )
            },
        )
