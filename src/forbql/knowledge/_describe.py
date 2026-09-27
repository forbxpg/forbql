"""A table as a profile sees it: columns, keys, joins, and the query for samples."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlglot import exp

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from forbql.firewall import ForeignKey, SchemaCatalog
    from forbql.policy import Engine, TableAccess

SAMPLES = 10
"""Values shown per sample column."""

SAMPLE_FLOOR = 5
"""Rows a value needs to be shown: rarer values could single a person out."""


@dataclass(frozen=True, slots=True)
class ColumnDescription:
    """One column a profile sees.

    Attributes:
        name: str - Column name.
        type: str - Type as the engine names it.
        nullable: bool - Whether it may hold NULL.
        comment: str | None - The database's comment; text from outside forbql.
        key: bool - Whether it is part of the primary key.
        pii: str | None - `mask` or `aggregate_only` when the policy says so.

    """

    name: str
    type: str
    nullable: bool
    comment: str | None
    key: bool
    pii: str | None


@dataclass(frozen=True, slots=True)
class TableDescription:
    """A table or view as a profile sees it.

    Attributes:
        table: str - `schema.table`.
        comment: str | None - The database's comment; text from outside forbql.
        view: bool - Whether it is a view.
        columns: tuple[ColumnDescription, ...] - Its visible columns, in order.
        joins: tuple[str, ...] - Join conditions to visible tables by foreign keys.
        samples: dict[str, tuple[str, ...]] - Frequent values of sample columns.

    """

    table: str
    comment: str | None
    view: bool
    columns: tuple[ColumnDescription, ...]
    joins: tuple[str, ...]
    samples: dict[str, tuple[str, ...]] = field(default_factory=dict)


def describe(
    catalog: SchemaCatalog,
    visible: Mapping[str, Sequence[str]],
    access: Mapping[str, TableAccess],
    table: str,
) -> TableDescription | None:
    """Describe a table within what a profile sees.

    Args:
        catalog: SchemaCatalog - The schema.
        visible: Mapping[str, Sequence[str]] - Columns the profile sees per table.
        access: Mapping[str, TableAccess] - The profile's tables in the policy.
        table: str - `schema.table`, or `table` in the default schema.

    Returns:
        TableDescription | None - The table; None when it is hidden or missing
            alike, so the answer never tells one from the other.

    """
    qualified = table if "." in table else f"{catalog.default_schema}.{table}"
    info = catalog.tables.get(qualified)
    seen = visible.get(qualified)
    if info is None or seen is None:
        return None
    rules = access[qualified].pii if qualified in access else {}
    columns = tuple(
        ColumnDescription(
            name=column.name,
            type=column.type,
            nullable=column.nullable,
            comment=column.comment,
            key=column.name in info.primary_key,
            pii=rules[column.name].pii_class.value if column.name in rules else None,
        )
        for column in info.columns
        if column.name in seen
    )
    return TableDescription(
        table=qualified,
        comment=info.comment,
        view=info.view,
        columns=columns,
        joins=tuple(_joins(catalog, visible, qualified)),
    )


def sample_query(table: str, column: str, engine: Engine) -> str:
    """Build the query for a column's frequent values.

    Args:
        table: str - `schema.table`.
        column: str - The column.
        engine: Engine - The connection's engine.

    Returns:
        str - Values held by at least `SAMPLE_FLOOR` rows, most frequent first.

    """
    value = exp.column(column, quoted=True)
    count = exp.Count(this=exp.Star())
    query = (
        exp
        .select(value, exp.alias_(count, "n"))
        .from_(exp.to_table(table, dialect=engine.value))
        .group_by(value)
        .having(exp.GTE(this=count.copy(), expression=exp.Literal.number(SAMPLE_FLOOR)))
        .order_by(exp.Ordered(this=exp.column("n"), desc=True))
        .limit(SAMPLES)
    )
    return query.sql(dialect=engine.value)


def _joins(
    catalog: SchemaCatalog,
    visible: Mapping[str, Sequence[str]],
    table: str,
) -> list[str]:
    """List the joins between a table and other visible tables, both ways.

    Args:
        catalog: SchemaCatalog - The schema.
        visible: Mapping[str, Sequence[str]] - Columns the profile sees per table.
        table: str - `schema.table`.

    Returns:
        list[str] - Conditions such as `a.x = b.y`, sorted.

    """
    found: set[str] = set()
    for source, info in catalog.tables.items():
        for key in info.foreign_keys:
            if table in {source, key.table} and _usable(key, source, visible):
                found.add(
                    " AND ".join(
                        f"{source}.{mine} = {key.table}.{theirs}"
                        for mine, theirs in zip(
                            key.columns,
                            key.references,
                            strict=True,
                        )
                    ),
                )
    return sorted(found)


def _usable(
    key: ForeignKey,
    source: str,
    visible: Mapping[str, Sequence[str]],
) -> bool:
    """Say whether a profile sees both ends of a foreign key.

    Args:
        key: ForeignKey - The key.
        source: str - The referencing table.
        visible: Mapping[str, Sequence[str]] - Columns the profile sees per table.

    Returns:
        bool - True if both tables and all their key columns are visible.

    """
    return (
        source in visible
        and key.table in visible
        and set(key.columns) <= set(visible[source])
        and set(key.references) <= set(visible[key.table])
    )
