"""Everything one check needs, derived once per connection and profile."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from forbql.policy import Limits, PiiClass, PiiRule, Profile

if TYPE_CHECKING:
    from ._dialects import DialectProfile
    from ._snapshot import SchemaSnapshot


@dataclass(frozen=True, slots=True, kw_only=True)
class Visibility:
    """Tables and columns a profile can see in one snapshot.

    Attributes:
        default_schema: str - Schema unqualified tables resolve to.
        columns: dict[str, tuple[str, ...]] - Visible columns per `schema.table`.
        pii: dict[tuple[str, str], PiiRule] - Rule per visible PII column.

    """

    default_schema: str
    columns: dict[str, tuple[str, ...]]
    pii: dict[tuple[str, str], PiiRule]

    @classmethod
    def build(cls, profile: Profile, snapshot: SchemaSnapshot) -> Visibility:
        """Intersect the profile with the snapshot and drop `deny` columns.

        A listed table or column missing from the snapshot is simply not visible.

        Args:
            profile: Profile - The profile.
            snapshot: SchemaSnapshot - The database schema.

        Returns:
            Visibility - What the profile can see.

        """
        columns: dict[str, tuple[str, ...]] = {}
        pii: dict[tuple[str, str], PiiRule] = {}
        for table, access in profile.tables.items():
            existing = snapshot.tables.get(table)
            if existing is None:
                continue

            listed = existing if access.columns == "*" else access.columns
            visible = tuple(
                column
                for column in listed
                if column in existing
                and (
                    column not in access.pii
                    or access.pii[column].pii_class is not PiiClass.DENY
                )
            )
            columns[table] = visible
            pii.update({
                (table, column): access.pii[column]
                for column in visible
                if column in access.pii
            })

        return cls(default_schema=snapshot.default_schema, columns=columns, pii=pii)

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
