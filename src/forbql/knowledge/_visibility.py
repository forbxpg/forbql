"""Which glossary terms and examples a profile may see.

An entry is seen only if its SQL passes the firewall under the profile and its text
names nothing the profile cannot see. The SQL is what the firewall reads; the text
around it is not, so names in the text are compared with the synced schema.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from ._file import Example, GlossaryTerm, KnowledgeError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from forbql.firewall import Firewall, SchemaCatalog
    from forbql.policy import Engine


_WORD = re.compile(r"\w+")


def glossary_query(term: GlossaryTerm, catalog: SchemaCatalog, engine: Engine) -> str:
    """Build the query the firewall checks a term's expression with.

    The expression is parsed on its own and placed into a query built from the tree,
    so no text in it can name another table, end the statement or hide a comment.

    Args:
        term: GlossaryTerm - The term; it must have `table` and `sql`.
        catalog: SchemaCatalog - The synced schema, where `table` must be.
        engine: Engine - The connection's engine; its dialect parses the expression.

    Returns:
        str - `SELECT <expression> FROM <table>`.

    Raises:
        KnowledgeError: If the term has no expression, names an unknown table, or its
            expression is not one expression over columns.

    """
    if term.table is None or term.sql is None:
        msg = f"{term.term!r} has no sql"
        raise KnowledgeError(msg)
    table = resolve_table(term.table, catalog)
    try:
        expression = sqlglot.parse_one(term.sql, read=engine.value, into=exp.Condition)
    except SqlglotError as error:
        msg = f"{term.term!r}: sql is not one expression: {error}"
        raise KnowledgeError(msg) from error
    if any(node.comments for node in expression.walk()):
        msg = f"{term.term!r}: sql holds a comment"
        raise KnowledgeError(msg)
    if expression.find(exp.Query) is not None:
        msg = f"{term.term!r}: sql holds a query; write it as an example"
        raise KnowledgeError(msg)
    query = exp.select(expression).from_(exp.to_table(table, dialect=engine.value))
    return query.sql(dialect=engine.value)


def resolve_table(name: str, catalog: SchemaCatalog) -> str:
    """Find a table of the synced schema by its name, schema-qualified or not.

    Args:
        name: str - `schema.table`, or `table` in the default schema.
        catalog: SchemaCatalog - The synced schema.

    Returns:
        str - `schema.table` as the catalog names it.

    Raises:
        KnowledgeError: If the synced schema has no such table.

    """
    qualified = name if "." in name else f"{catalog.default_schema}.{name}"
    if qualified not in catalog.tables:
        msg = f"table {name} is not in the synced schema"
        raise KnowledgeError(msg)
    return qualified


def hidden_names(
    catalog: SchemaCatalog,
    visible: Mapping[str, Sequence[str]],
) -> frozenset[str]:
    """Collect the table and column names a profile sees nowhere, in lower case.

    A name the profile sees in some table (`id`, say) is not hidden, even where
    another table's column of that name is.

    Args:
        catalog: SchemaCatalog - The synced schema.
        visible: Mapping[str, Sequence[str]] - Columns the profile sees per table.

    Returns:
        frozenset[str] - Names that must not reach the profile.

    """
    everything = {
        name.casefold()
        for table, info in catalog.tables.items()
        for name in (table.rpartition(".")[2], *(c.name for c in info.columns))
    }
    seen = {
        name.casefold()
        for table, columns in visible.items()
        for name in (table.rpartition(".")[2], *columns)
    }
    return frozenset(everything - seen)


def mentions(text: str, hidden: frozenset[str]) -> list[str]:
    """Find hidden names in a text, as whole words and ignoring case.

    Args:
        text: str - The text.
        hidden: frozenset[str] - Names the profile must not see.

    Returns:
        list[str] - The hidden names the text holds, sorted.

    """
    folded = text.casefold()
    words = set(_WORD.findall(folded))
    return sorted(
        name
        for name in hidden
        if (name in words if _WORD.fullmatch(name) else name in folded)
    )


def why_hidden(  # ruff: ignore[too-many-arguments] - the entry and who asks
    entry: GlossaryTerm | Example,
    query: str | None,
    *,
    firewall: Firewall,
    connection: str,
    profile: str,
    hidden: frozenset[str],
) -> str | None:
    """Say why a profile may not see an entry, if it may not.

    Args:
        entry: GlossaryTerm | Example - The entry.
        query: str | None - What the firewall checks: the term's built query or the
            example's SQL; None for a term without SQL.
        firewall: Firewall - Firewall with the connection's schema.
        connection: str - Connection name.
        profile: str - Who asks.
        hidden: frozenset[str] - Names the profile sees nowhere.

    Returns:
        str | None - The reason, for the operator; None when the profile may see it.

    """
    if found := mentions(entry.text, hidden):
        return f"it names {', '.join(found)}"
    if query is None:
        return None
    verdict = firewall.check(query, connection=connection, profile=profile)
    # Without a schema the firewall checks structure only: that proves nothing here.
    if verdict.structural_only:
        return "there is no synced schema to check it against"
    if not verdict.allowed:
        return "the firewall refuses it: " + "; ".join(
            v.message for v in verdict.violations
        )
    return None


def allowed[E: (GlossaryTerm, Example)](  # ruff: ignore[too-many-arguments] - the entries and who asks
    entries: Sequence[E],
    *,
    firewall: Firewall,
    connection: str,
    profile: str,
    catalog: SchemaCatalog,
    engine: Engine,
) -> list[E]:
    """Keep the entries a profile may see.

    A term whose table left the schema since it was loaded is not seen: its
    expression cannot be checked any more.

    Args:
        entries: Sequence[E] - Terms or examples.
        firewall: Firewall - Firewall with the connection's schema.
        connection: str - Connection name.
        profile: str - Who asks.
        catalog: SchemaCatalog - The synced schema.
        engine: Engine - The connection's engine.

    Returns:
        list[E] - The entries the profile may see, in their order.

    """
    hidden = hidden_names(catalog, firewall.visible(connection, profile))
    kept: list[E] = []
    for entry in entries:
        try:
            query = (
                glossary_query(entry, catalog, engine)
                if isinstance(entry, GlossaryTerm) and entry.sql
                else entry.sql
            )
        except KnowledgeError:
            continue
        reason = why_hidden(
            entry,
            query,
            firewall=firewall,
            connection=connection,
            profile=profile,
            hidden=hidden,
        )
        if reason is None:
            kept.append(entry)
    return kept
