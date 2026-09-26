"""Entity-relationship diagrams in Mermaid, showing only what a profile can see."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from forbql.firewall import ForeignKey, SchemaCatalog

MAX_TABLES = 40
"""Past this, a diagram is drawn only around chosen tables."""

_NOT_A_WORD = re.compile(r"[^A-Za-z0-9_]+")


def erd(
    catalog: SchemaCatalog,
    visible: Mapping[str, Sequence[str]],
    *,
    around: Sequence[str] = (),
    depth: int = 1,
) -> str:
    """Draw the visible tables, their columns and the references between them.

    Args:
        catalog: SchemaCatalog - The schema.
        visible: Mapping[str, Sequence[str]] - Columns a profile sees per table.
        around: Sequence[str] - Tables to centre on; unqualified names are in the
            default schema. None draws everything.
        depth: int - How many references away from those tables to go.

    Returns:
        str - A Mermaid `erDiagram`.

    Raises:
        ValueError: If a chosen table is not visible, or there are too many tables
            and none was chosen.

    """
    tables = {name: tuple(visible[name]) for name in catalog.tables if name in visible}
    edges = [
        (name, key)
        for name in tables
        for key in catalog.tables[name].foreign_keys
        if key.table in tables
        and set(key.columns) <= set(tables[name])
        and set(key.references) <= set(tables[key.table])
    ]
    if around:
        kept = _around(catalog.default_schema, tables, edges, around, depth)
    elif len(tables) > MAX_TABLES:
        msg = f"{len(tables)} tables are too many for one diagram: choose some"
        raise ValueError(msg)
    else:
        kept = set(tables)
    lines = ["erDiagram"]
    for name in sorted(kept):
        info = catalog.tables[name]
        keyed = {column for _, key in edges if _ == name for column in key.columns}
        lines.append(f'    {_word(name)}["{name}"] {{')
        for column in info.columns:
            if column.name not in tables[name]:
                continue
            marks = [
                mark
                for mark, marked in (
                    ("PK", column.name in info.primary_key),
                    ("FK", column.name in keyed),
                )
                if marked
            ]
            suffix = f" {', '.join(marks)}" if marks else ""
            # A quoted name may hold spaces or dashes: the word goes first, the name
            # itself into the attribute's comment.
            named = f' "{column.name}"' if _word(column.name) != column.name else ""
            kind = _word(column.type) or "any"
            lines.append(f"        {kind} {_word(column.name)}{suffix}{named}")
        lines.append("    }")
    lines.extend(
        f'    {_word(key.table)} ||--o{{ {_word(name)} : "{", ".join(key.columns)}"'
        for name, key in sorted(edges, key=lambda edge: (edge[0], edge[1].columns))
        if name in kept and key.table in kept
    )
    return "\n".join(lines) + "\n"


def _around(
    default_schema: str,
    tables: Mapping[str, Sequence[str]],
    edges: Sequence[tuple[str, ForeignKey]],
    around: Sequence[str],
    depth: int,
) -> set[str]:
    """Collect the chosen tables and those within `depth` references of them.

    Args:
        default_schema: str - Schema of unqualified names.
        tables: Mapping[str, Sequence[str]] - Visible tables.
        edges: Sequence[tuple[str, ForeignKey]] - Visible references.
        around: Sequence[str] - Chosen tables.
        depth: int - How far to go.

    Returns:
        set[str] - Tables to draw.

    Raises:
        ValueError: If a chosen table is not visible.

    """
    chosen = {name if "." in name else f"{default_schema}.{name}" for name in around}
    if missing := sorted(chosen - set(tables)):
        msg = f"no visible table {', '.join(missing)}"
        raise ValueError(msg)
    kept = set(chosen)
    for _ in range(depth):
        kept |= {
            other
            for name, key in edges
            for one, other in ((name, key.table), (key.table, name))
            if one in kept
        }
    return kept


def _word(text: str) -> str:
    """Make text a Mermaid word: letters, digits and underscores.

    Args:
        text: str - A table name or a type.

    Returns:
        str - The word.

    """
    return _NOT_A_WORD.sub("_", text).strip("_")
