"""What changed between two versions of a schema, one line per change."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from forbql.firewall import ColumnInfo, ForeignKey, SchemaCatalog, TableInfo


def diff_catalogs(old: SchemaCatalog, new: SchemaCatalog) -> list[str]:
    """List the changes from one catalog to the next.

    Lines start with `+` for something added, `-` for something removed and `~` for
    something changed, and come in table order.

    Args:
        old: SchemaCatalog - The earlier version.
        new: SchemaCatalog - The later version.

    Returns:
        list[str] - The changes; empty when the schemas are the same.

    """
    changes: list[str] = []
    if old.default_schema != new.default_schema:
        schemas = f"{old.default_schema} -> {new.default_schema}"
        changes.append(f"~ default schema: {schemas}")
    for name in sorted(old.tables.keys() | new.tables.keys()):
        before, after = old.tables.get(name), new.tables.get(name)
        if before is None and after is not None:
            changes.append(f"+ {_kind(after)} {name}")
        elif after is None and before is not None:
            changes.append(f"- {_kind(before)} {name}")
        elif before is not None and after is not None:
            changes.extend(_table_changes(name, before, after))
    return changes


def _kind(table: TableInfo) -> str:
    return "view" if table.view else "table"


def _table_changes(name: str, before: TableInfo, after: TableInfo) -> list[str]:
    """List the changes inside one table or view.

    Args:
        name: str - `schema.table`.
        before: TableInfo - The earlier version.
        after: TableInfo - The later version.

    Returns:
        list[str] - The changes.

    """
    old = {column.name: column for column in before.columns}
    new = {column.name: column for column in after.columns}
    kinds = [f"~ {_kind(after)} {name}: was a {_kind(before)}"]
    changes = kinds if before.view != after.view else []
    changes += [
        f"+ column {name}.{column.name} {column.type}"
        for column in after.columns
        if column.name not in old
    ]
    changes.extend(
        f"- column {name}.{column.name}"
        for column in before.columns
        if column.name not in new
    )
    for column in after.columns:
        if column.name in old:
            changes.extend(
                _column_changes(f"{name}.{column.name}", old[column.name], column),
            )
    if before.primary_key != after.primary_key:
        keys = f"({', '.join(before.primary_key)}) -> ({', '.join(after.primary_key)})"
        changes.append(f"~ {_kind(after)} {name}: primary key {keys}")
    changes.extend(
        f"- foreign key {name} {_key(key)}"
        for key in before.foreign_keys
        if key not in after.foreign_keys
    )
    changes.extend(
        f"+ foreign key {name} {_key(key)}"
        for key in after.foreign_keys
        if key not in before.foreign_keys
    )
    if before.comment != after.comment:
        changes.append(f"~ {_kind(after)} {name}: comment")
    if before.definition != after.definition:
        changes.append(f"~ {_kind(after)} {name}: definition")
    return changes


def _column_changes(name: str, before: ColumnInfo, after: ColumnInfo) -> list[str]:
    """List the changes of one column.

    Args:
        name: str - `schema.table.column`.
        before: ColumnInfo - The earlier version.
        after: ColumnInfo - The later version.

    Returns:
        list[str] - The changes.

    """
    changes: list[str] = []
    if before.type != after.type:
        changes.append(f"~ column {name}: type {before.type} -> {after.type}")
    if before.nullable != after.nullable:
        now = "nullable" if after.nullable else "not null"
        changes.append(f"~ column {name}: now {now}")
    if before.comment != after.comment:
        changes.append(f"~ column {name}: comment")
    return changes


def _key(key: ForeignKey) -> str:
    return f"({', '.join(key.columns)}) -> {key.table} ({', '.join(key.references)})"
