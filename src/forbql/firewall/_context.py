"""Everything one check needs, derived once per connection and profile."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from forbql.policy import Limits, PiiClass, PiiRule, Profile

if TYPE_CHECKING:
    from collections.abc import Callable

    from ._dialects import DialectProfile
    from ._snapshot import SchemaSnapshot


@dataclass(frozen=True, slots=True, kw_only=True)
class Visibility:
    """Tables and columns a profile can see in one snapshot.

    Attributes:
        default_schema: str - Schema unqualified tables resolve to.
        columns: dict[str, tuple[str, ...]] - Visible columns per `schema.table`,
            written as the parsed query writes names.
        pii: dict[tuple[str, str], PiiRule] - Rule per visible PII column, written so.
        named: dict[str, tuple[str, ...]] - The same columns under the names the
            database uses, for callers outside the firewall.

    """

    default_schema: str
    columns: dict[str, tuple[str, ...]]
    pii: dict[tuple[str, str], PiiRule]
    named: dict[str, tuple[str, ...]]

    @classmethod
    def build(
        cls,
        profile: Profile,
        snapshot: SchemaSnapshot,
        fold: Callable[[str], str] = str,
    ) -> Visibility:
        """Intersect the profile with the snapshot and drop `deny` columns.

        A listed table or column missing from the snapshot is simply not visible.
        Names are compared folded, as the engine compares them.

        Args:
            profile: Profile - The profile.
            snapshot: SchemaSnapshot - The database schema.
            fold: Callable[[str], str] - Writes a name as the parsed query does.

        Returns:
            Visibility - What the profile can see.

        """
        tables = {fold(name): name for name in snapshot.tables}
        columns: dict[str, tuple[str, ...]] = {}
        named: dict[str, tuple[str, ...]] = {}
        pii: dict[tuple[str, str], PiiRule] = {}
        for listed_table, access in profile.tables.items():
            table = tables.get(fold(listed_table))
            if table is None:
                continue
            existing = {fold(column): column for column in snapshot.tables[table]}
            rules = {fold(column): rule for column, rule in access.pii.items()}
            listed = existing.values() if access.columns == "*" else access.columns
            visible = [
                existing[folded]
                for folded in dict.fromkeys(fold(column) for column in listed)
                if folded in existing
                and (
                    folded not in rules or rules[folded].pii_class is not PiiClass.DENY
                )
            ]
            key = fold(table)
            columns[key] = tuple(fold(column) for column in visible)
            named[table] = tuple(visible)
            pii.update({
                (key, fold(column)): rules[fold(column)]
                for column in visible
                if fold(column) in rules
            })

        return cls(
            default_schema=fold(snapshot.default_schema),
            columns=columns,
            pii=pii,
            named=named,
        )

    def sqlglot_schema(self) -> dict[str, object]:
        """Return the visible schema in the nested form sqlglot's qualifier takes.

        Types are unknown on purpose: no rule depends on them.

        Returns:
            dict[str, object] - `{schema: {table: {column: type}}}`.

        """
        nested: dict[str, dict[str, dict[str, str]]] = {}
        for table, columns in self.columns.items():
            schema, name = table.split(".")
            nested.setdefault(schema, {})[name] = dict.fromkeys(columns, "UNKNOWN")

        return dict(nested)


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckContext:
    """Inputs of one check.

    Attributes:
        dialect: DialectProfile - Engine facts.
        limits: Limits - Bounds of the profile.
        allow_recursive_cte: bool - Whether `WITH RECURSIVE` is allowed.
        functions: frozenset[str] - Allowed function names, upper case.
        visibility: Visibility | None - What the profile sees; None in structural mode.

    """

    dialect: DialectProfile
    limits: Limits = field(default_factory=Limits)
    allow_recursive_cte: bool = False
    functions: frozenset[str]
    visibility: Visibility | None = None

    @property
    def sqlglot_dialect(self) -> str:
        """Name of the sqlglot dialect.

        Returns:
            str - The dialect name.

        """
        return self.dialect.engine.value
