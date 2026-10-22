"""Everything one check needs, derived once per connection and profile."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from forbql.policy import Limits, PiiClass, PiiRule, Profile

if TYPE_CHECKING:
    from collections.abc import Callable

    from ._dialects import DialectProfile
    from ._snapshot import SchemaSnapshot

# deny is stricter than aggregate_only, which is stricter than mask, which is
# stricter than a column with no PII class.
_STRICTNESS = (None, PiiClass.MASK, PiiClass.AGGREGATE_ONLY, PiiClass.DENY)
_EXPRESSION_DIALECTS = ("postgres", "mysql", "sqlite")


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
        """Intersect the profile with the snapshot and drop hidden columns.

        A listed table or column missing from the snapshot is simply not visible.
        Names are compared folded, as the engine compares them. A `deny` column is
        dropped. So is a generated column whose expression cannot be read or parsed,
        reads a column that is not visible, or reads a column with a stricter PII
        class than its own.

        Args:
            profile: Profile - The profile.
            snapshot: SchemaSnapshot - The database schema.
            fold: Callable[[str], str] - Writes a name as the parsed query does.

        Returns:
            Visibility - What the profile can see.

        """
        opened = _Opened(snapshot, fold)
        tables = {fold(name): name for name in snapshot.tables}
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
            opened.columns[key] = tuple(fold(column) for column in visible)
            opened.named[table] = tuple(visible)
            opened.pii.update({
                (key, fold(column)): rules[fold(column)]
                for column in visible
                if fold(column) in rules
            })
            opened.classes.update({
                (key, fold(column)): rules[fold(column)].pii_class
                if fold(column) in rules
                else None
                for column in visible
            })
        opened.hide_generated()
        return cls(
            default_schema=fold(snapshot.default_schema),
            columns=opened.columns,
            pii=opened.pii,
            named=opened.named,
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


@dataclass(frozen=True, slots=True)
class _Ref:
    """One column a generation expression mentions.

    Attributes:
        schema: str - Schema or database qualifier; empty when unqualified.
        table: str - Table qualifier; empty when the column is unqualified.
        column: str - Column name, as the expression wrote it.

    """

    schema: str
    table: str
    column: str


class _Opened:
    """Columns a profile can see, while generated columns are still being judged."""

    snapshot: SchemaSnapshot
    fold: Callable[[str], str]
    columns: dict[str, tuple[str, ...]]
    named: dict[str, tuple[str, ...]]
    pii: dict[tuple[str, str], PiiRule]
    classes: dict[tuple[str, str], PiiClass | None]

    def __init__(self, snapshot: SchemaSnapshot, fold: Callable[[str], str]) -> None:
        """Start from nothing visible.

        Args:
            snapshot: SchemaSnapshot - The database schema, including expressions.
            fold: Callable[[str], str] - Writes a name as the parsed query does.

        """
        self.snapshot = snapshot
        self.fold = fold
        self.columns = {}
        self.named = {}
        self.pii = {}
        self.classes = {}

    def hide_generated(self) -> None:
        """Drop generated columns that would copy a hidden or stricter column.

        A column stays only when its expression parses and every column it reads
        is visible, on that same table or unambiguously elsewhere, and no source
        has a stricter PII class. Dropping one column can hide another that copies
        it, so this repeats until nothing else goes.

        """
        changed = True
        while changed:
            changed = False
            for table, visible in list(self.named.items()):
                kept = tuple(
                    column
                    for column in visible
                    if self._expression_allows(table, column)
                )
                if kept == visible:
                    continue
                changed = True
                self._drop(table, visible, kept)

    def _drop(
        self,
        table: str,
        visible: tuple[str, ...],
        kept: tuple[str, ...],
    ) -> None:
        """Remove columns that this pass rejected.

        Args:
            table: str - Table as `schema.table`.
            visible: tuple[str, ...] - Columns visible at the start of the pass.
            kept: tuple[str, ...] - Columns that may stay.

        """
        key = self.fold(table)
        removed = {self.fold(column) for column in visible} - {
            self.fold(column) for column in kept
        }
        self.named[table] = kept
        self.columns[key] = tuple(self.fold(column) for column in kept)
        for column in removed:
            _ = self.pii.pop((key, column), None)
            _ = self.classes.pop((key, column), None)

    def _expression_allows(self, table: str, column: str) -> bool:
        """Tell whether one visible column may stay, given what is visible now.

        Args:
            table: str - Table as `schema.table`.
            column: str - Column name as the database stores it.

        Returns:
            bool - True when the column is ordinary, or its sources are safe.

        """
        generated, expression = _generation(self.snapshot, self.fold, table, column)
        if not generated:
            return True
        refs = None if expression is None else _column_refs(expression)
        if refs is None:
            return False
        own = self.classes.get((self.fold(table), self.fold(column)))
        for ref in refs:
            source = _resolve(ref, table, self.snapshot, self.fold)
            if source is None or not _source_allows(
                source,
                own,
                self.named,
                self.classes,
                self.fold,
            ):
                return False
        return True


def _generation(
    snapshot: SchemaSnapshot,
    fold: Callable[[str], str],
    table: str,
    column: str,
) -> tuple[bool, str | None]:
    """Return whether a column is generated, and its expression when known.

    Args:
        snapshot: SchemaSnapshot - The database schema.
        fold: Callable[[str], str] - Writes a name as the parsed query does.
        table: str - Table as `schema.table`.
        column: str - Column name as the database stores it.

    Returns:
        tuple[bool, str | None] - False when the column is stored. True and None
            when it is generated and the expression was not readable.

    """
    for name, expression in snapshot.generated.get(table, {}).items():
        if fold(name) == fold(column):
            text = expression.strip() if expression is not None else None
            return True, text or None
    return False, None


def _source_allows(
    source: tuple[str, str],
    own: PiiClass | None,
    named: dict[str, tuple[str, ...]],
    classes: dict[tuple[str, str], PiiClass | None],
    fold: Callable[[str], str],
) -> bool:
    """Tell whether a resolved source is visible and no stricter than the copy.

    Args:
        source: tuple[str, str] - Table as `schema.table`, and the folded column.
        own: PiiClass | None - PII class of the generated column.
        named: dict[str, tuple[str, ...]] - Columns still visible.
        classes: dict[tuple[str, str], PiiClass | None] - Their PII classes.
        fold: Callable[[str], str] - Writes a name as the parsed query does.

    Returns:
        bool - True when the source may feed the generated column.

    """
    table, column = source
    visible = {fold(name) for name in named.get(table, ())}
    if column not in visible:
        return False
    source_class = classes.get((fold(table), column))
    return _STRICTNESS.index(source_class) <= _STRICTNESS.index(own)


def _column_refs(expression: str) -> tuple[_Ref, ...] | None:
    """Find column references in a generation expression.

    Each dialect that accepts the text contributes. A reference any of them sees
    counts, so a dialect that hides a name inside a string cannot drop it. None
    means the text cannot be parsed, or it contains a star.

    Args:
        expression: str - The generation expression.

    Returns:
        tuple[_Ref, ...] | None - The references, or None when the expression is
            not safe to trust.

    """
    found: dict[tuple[str, str, str], _Ref] = {}
    parsed = False
    for dialect in _EXPRESSION_DIALECTS:
        try:
            tree = sqlglot.parse_one(expression, read=dialect)
        except SqlglotError:
            continue
        parsed = True
        if next(tree.find_all(exp.Star), None) is not None:
            return None
        for column in tree.find_all(exp.Column):
            ref = _ref(column)
            if ref is None:
                return None
            found[ref.schema, ref.table, ref.column] = ref
    if not parsed:
        return None
    return tuple(found.values())


def _ref(column: exp.Column) -> _Ref | None:
    """Read a column reference's qualifiers.

    Args:
        column: exp.Column - A column node.

    Returns:
        _Ref | None - The reference, or None when it has no name.

    """
    if not column.name:
        return None
    return _Ref(column.db or "", column.table or "", column.name)


def _resolve(
    ref: _Ref,
    table: str,
    snapshot: SchemaSnapshot,
    fold: Callable[[str], str],
) -> tuple[str, str] | None:
    """Resolve a reference to one column of the snapshot.

    An unqualified name binds to the generated column's own table when that
    table has it. Otherwise, and for a qualified name, it must name exactly one
    table. The generated column's own table wins when a qualifier names it.

    Args:
        ref: _Ref - The reference.
        table: str - Table that owns the generated column, `schema.table`.
        snapshot: SchemaSnapshot - The database schema.
        fold: Callable[[str], str] - Writes a name as the parsed query does.

    Returns:
        tuple[str, str] | None - Table and folded column, or None when the
            reference is missing or ambiguous.

    """
    if not ref.table:
        found = _column_on(snapshot, table, ref.column, fold)
        if found is not None:
            return table, found
        owners = [
            full
            for full in snapshot.tables
            if _column_on(snapshot, full, ref.column, fold) is not None
        ]
        if len(owners) != 1:
            return None
        column = _column_on(snapshot, owners[0], ref.column, fold)
        return None if column is None else (owners[0], column)
    matches = _tables_named(ref, table, snapshot, fold)
    if len(matches) != 1:
        return None
    column = _column_on(snapshot, matches[0], ref.column, fold)
    return None if column is None else (matches[0], column)


def _tables_named(
    ref: _Ref,
    current: str,
    snapshot: SchemaSnapshot,
    fold: Callable[[str], str],
) -> list[str]:
    """Find tables a qualifier names, preferring the generated column's table.

    Args:
        ref: _Ref - The reference; its table qualifier is set.
        current: str - Table that owns the generated column.
        snapshot: SchemaSnapshot - The database schema.
        fold: Callable[[str], str] - Writes a name as the parsed query does.

    Returns:
        list[str] - The one table to use, or empty when none or several match.

    """
    matches = [full for full in snapshot.tables if _name_matches(full, ref, fold)]
    if current in matches:
        return [current]
    if len(matches) == 1:
        return matches
    return []


def _name_matches(full: str, ref: _Ref, fold: Callable[[str], str]) -> bool:
    """Tell whether a `schema.table` key is the table a qualifier names.

    Args:
        full: str - Snapshot key, `schema.table`.
        ref: _Ref - The reference.
        fold: Callable[[str], str] - Writes a name as the parsed query does.

    Returns:
        bool - True when the table name matches, and the schema too if given.

    """
    schema, name = full.split(".", 1)
    if fold(name) != fold(ref.table):
        return False
    return not ref.schema or fold(schema) == fold(ref.schema)


def _column_on(
    snapshot: SchemaSnapshot,
    table: str,
    column: str,
    fold: Callable[[str], str],
) -> str | None:
    """Return a column's folded name when the table has it.

    Args:
        snapshot: SchemaSnapshot - The database schema.
        table: str - Table as `schema.table`.
        column: str - Column name from the expression.
        fold: Callable[[str], str] - Writes a name as the parsed query does.

    Returns:
        str | None - The folded name, or None when the table has no such column.

    """
    folded = fold(column)
    for name in snapshot.tables.get(table, ()):
        if fold(name) == folded:
            return folded
    return None
