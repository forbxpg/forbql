"""The set schema search is measured on: tests/data/search."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml

from forbql.firewall import ColumnInfo, ForeignKey, SchemaCatalog, TableInfo

DATA = Path(__file__).parents[1] / "data" / "search"


@dataclass(frozen=True, slots=True)
class Question:
    text: str
    tables: frozenset[str]


def eval_catalog() -> SchemaCatalog:
    raw = cast("dict[str, object]", yaml.safe_load((DATA / "schema.yaml").read_text()))
    tables = cast("dict[str, dict[str, object]]", raw["tables"])
    return SchemaCatalog(
        default_schema=str(raw["default_schema"]),
        tables={name: _table(spec) for name, spec in tables.items()},
    )


def eval_questions() -> list[Question]:
    raw = cast(
        "dict[str, list[dict[str, object]]]",
        yaml.safe_load((DATA / "questions.yaml").read_text()),
    )
    return [
        Question(
            text=str(item["q"]),
            tables=frozenset(cast("list[str]", item["tables"])),
        )
        for item in raw["questions"]
    ]


def _table(spec: dict[str, object]) -> TableInfo:
    columns: list[ColumnInfo] = []
    for text in cast("list[str]", spec["columns"]):
        name, kind, *comment = text.split(" ", 2)
        columns.append(
            ColumnInfo(
                name=name,
                type=kind,
                nullable=True,
                comment=comment[0] if comment else None,
            ),
        )
    references = cast("dict[str, str]", spec.get("fk") or {})
    return TableInfo(
        columns=tuple(columns),
        primary_key=("id",) if any(c.name == "id" for c in columns) else (),
        foreign_keys=tuple(
            ForeignKey(
                columns=(own,),
                table=target,
                references=("code",) if own == "currency" else ("id",),
            )
            for own, target in references.items()
        ),
        comment=str(spec["comment"]),
    )
