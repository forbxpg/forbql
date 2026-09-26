"""Putting an engine's introspection together into a catalog."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from forbql.firewall import ColumnInfo, ForeignKey, SchemaCatalog, TableInfo

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(slots=True)
class Relation:
    """What an engine read about one table or view.

    Attributes:
        columns: list[ColumnInfo] - The columns the role may read, in order.
        comment: str | None - The database's comment.
        view: bool - Whether it is a view.
        definition: str | None - A view's query, if the role may read it.
        primary_key: tuple[str, ...] - Primary key columns.
        foreign_keys: list[ForeignKey] - References to other tables.

    """

    columns: list[ColumnInfo] = field(default_factory=list)
    comment: str | None = None
    view: bool = False
    definition: str | None = None
    primary_key: tuple[str, ...] = ()
    foreign_keys: list[ForeignKey] = field(default_factory=list)


def assemble(default_schema: str, relations: dict[str, Relation]) -> SchemaCatalog:
    """Build the catalog, keeping only what the role can see.

    A table without readable columns is left out, and so is a key that names a column
    or table left out: a key must not reveal what the role cannot read.

    Args:
        default_schema: str - Schema unqualified tables resolve to.
        relations: dict[str, Relation] - What the engine read, by `schema.table`.

    Returns:
        SchemaCatalog - The catalog.

    """
    visible = {
        name: {column.name for column in relation.columns}
        for name, relation in relations.items()
        if relation.columns
    }

    def readable(table: str, columns: Sequence[str]) -> bool:
        return table in visible and set(columns) <= visible[table]

    return SchemaCatalog(
        default_schema=default_schema,
        tables={
            name: TableInfo(
                columns=tuple(relation.columns),
                primary_key=relation.primary_key
                if readable(name, relation.primary_key)
                else (),
                foreign_keys=tuple(
                    key
                    for key in relation.foreign_keys
                    if readable(name, key.columns)
                    and readable(key.table, key.references)
                ),
                comment=relation.comment or None,
                view=relation.view,
                definition=relation.definition,
            )
            for name, relation in relations.items()
            if name in visible
        },
    )
