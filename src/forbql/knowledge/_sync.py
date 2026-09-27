"""Loading the knowledge file: who sees each entry, and what the store takes in."""

from __future__ import annotations

from asyncio import to_thread
from dataclasses import dataclass
from typing import TYPE_CHECKING

from forbql.firewall import Firewall
from forbql.store import StoredExample, StoredTerm

from ._file import Example, GlossaryTerm, KnowledgeError
from ._visibility import (
    allowed,
    glossary_query,
    hidden_names,
    resolve_table,
    why_hidden,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from forbql.firewall import SchemaCatalog
    from forbql.policy import Policy
    from forbql.store import Store

    from ._embed import Embedder
    from ._file import KnowledgeFile


@dataclass(frozen=True, slots=True)
class Reach:
    """Which profiles see an entry, and why the others do not.

    Attributes:
        label: str - The entry, as the operator reads it.
        seen: tuple[str, ...] - Profiles that see it.
        hidden: dict[str, str] - Why each other profile does not.

    """

    label: str
    seen: tuple[str, ...]
    hidden: dict[str, str]


@dataclass(frozen=True, slots=True)
class KnowledgeChange:
    """What a load did to the store.

    Attributes:
        added: tuple[str, ...] - Entries new to the store.
        changed: tuple[str, ...] - Entries written again.
        removed: tuple[str, ...] - Entries gone from the file, so from the store.
        embedded: int - Entries embedded now.

    """

    added: tuple[str, ...]
    changed: tuple[str, ...]
    removed: tuple[str, ...]
    embedded: int


def label(entry: GlossaryTerm | Example) -> str:
    """Name an entry for the operator.

    Args:
        entry: GlossaryTerm | Example - The entry.

    Returns:
        str - `glossary '<term>'` or `example '<question>'`.

    """
    kind = "glossary" if isinstance(entry, GlossaryTerm) else "example"
    return f"{kind} {entry.key!r}"


def resolved(
    knowledge: KnowledgeFile,
    catalog: SchemaCatalog,
) -> tuple[list[GlossaryTerm], list[Example]]:
    """Name every term's table as the synced schema does.

    Args:
        knowledge: KnowledgeFile - The file.
        catalog: SchemaCatalog - The synced schema.

    Returns:
        tuple[list[GlossaryTerm], list[Example]] - Terms with `schema.table`, and
            the examples as they are; `resolve_table` refuses an unknown table.

    """
    terms = [
        term.model_copy(update={"table": resolve_table(term.table, catalog)})
        if term.table
        else term
        for term in knowledge.glossary
    ]
    return terms, list(knowledge.examples)


def reach(
    entries: Sequence[GlossaryTerm | Example],
    *,
    policy: Policy,
    connection: str,
    catalog: SchemaCatalog,
) -> list[Reach]:
    """Check every entry under every profile of the connection.

    Args:
        entries: Sequence[GlossaryTerm | Example] - The entries.
        policy: Policy - The policy.
        connection: str - Connection name.
        catalog: SchemaCatalog - The synced schema the firewall checks against.

    Returns:
        list[Reach] - Who sees each entry, in the entries' order.

    Raises:
        KnowledgeError: If a term's expression cannot be built; every one is named.

    """
    engine = policy.connection(connection).engine
    firewall = Firewall(policy, {connection: catalog.snapshot()})
    profiles = sorted(policy.connection(connection).profiles)
    hidden = {
        profile: hidden_names(catalog, firewall.visible(connection, profile))
        for profile in profiles
    }
    queries: list[str | None] = []
    problems: list[str] = []
    for entry in entries:
        try:
            queries.append(
                entry.sql
                if isinstance(entry, Example)
                else glossary_query(entry, catalog, engine)
                if entry.sql
                else None,
            )
        except KnowledgeError as error:
            problems.append(str(error))
    if problems:
        raise KnowledgeError("\n".join(problems))
    found: list[Reach] = []
    for entry, query in zip(entries, queries, strict=True):
        reasons = {
            profile: why_hidden(
                entry,
                query,
                firewall=firewall,
                connection=connection,
                profile=profile,
                hidden=hidden[profile],
            )
            for profile in profiles
        }
        found.append(
            Reach(
                label=label(entry),
                seen=tuple(p for p, why in reasons.items() if why is None),
                hidden={p: why for p, why in reasons.items() if why is not None},
            ),
        )
    return found


def unseen(
    entries: Sequence[GlossaryTerm | Example],
    *,
    policy: Policy,
    connection: str,
    catalog: SchemaCatalog,
) -> list[str]:
    """Find the entries no profile may see any more, as after a schema change.

    Args:
        entries: Sequence[GlossaryTerm | Example] - The loaded entries.
        policy: Policy - The policy.
        connection: str - Connection name.
        catalog: SchemaCatalog - The schema they are checked against now.

    Returns:
        list[str] - Their labels, in the entries' order.

    """
    firewall = Firewall(policy, {connection: catalog.snapshot()})
    engine = policy.connection(connection).engine
    seen = {
        label(entry)
        for profile in policy.connection(connection).profiles
        for entry in allowed(
            entries,
            firewall=firewall,
            connection=connection,
            profile=profile,
            catalog=catalog,
            engine=engine,
        )
    }
    return [label(entry) for entry in entries if label(entry) not in seen]


async def index_knowledge(  # ruff: ignore[too-many-arguments] - the entries and where they go
    store: Store,
    embedder: Embedder,
    connection: str,
    terms: Sequence[GlossaryTerm],
    examples: Sequence[Example],
    *,
    everything: bool = False,
) -> KnowledgeChange:
    """Make the store hold exactly these entries, embedding only what changed.

    Approved proposals stay: only entries the knowledge file put there are removed.

    Args:
        store: Store - The store.
        embedder: Embedder - The model.
        connection: str - Connection name.
        terms: Sequence[GlossaryTerm] - Terms, their tables resolved.
        examples: Sequence[Example] - Examples.
        everything: bool - Embed every entry again, as after a change of model.

    Returns:
        KnowledgeChange - What was added, changed, removed and embedded.

    """
    held = {
        ("glossary", t.term): (t.body_hash, t.model)
        for t in await store.knowledge.terms(connection)
    } | {
        ("example", e.question): (e.body_hash, e.model)
        for e in await store.knowledge.examples(connection)
        # Approved proposals are the operator's decisions, not the file's to remove.
        if e.proposal is None
    }
    entries: list[GlossaryTerm | Example] = [*terms, *examples]
    keys = {(_kind(entry), entry.key): entry for entry in entries}
    fresh = [
        entry
        for key, entry in keys.items()
        if everything or held.get(key) != (entry.body_hash, embedder.name)
    ]
    removed = sorted(held.keys() - keys.keys())
    # Nothing to embed, nothing to load: the model takes seconds to start.
    vectors = (
        await to_thread(embedder.documents, [e.body for e in fresh]) if fresh else []
    )
    written = list(zip(fresh, vectors, strict=True))
    await store.knowledge.update(
        connection,
        terms=[
            (_stored_term(entry, embedder.name), vector)
            for entry, vector in written
            if isinstance(entry, GlossaryTerm)
        ],
        examples=[
            (_stored_example(entry, embedder.name), vector)
            for entry, vector in written
            if isinstance(entry, Example)
        ],
        removed_terms=[key for kind, key in removed if kind == "glossary"],
        removed_examples=[key for kind, key in removed if kind == "example"],
    )
    return KnowledgeChange(
        added=tuple(label(e) for e in fresh if (_kind(e), e.key) not in held),
        changed=tuple(
            label(e)
            for e in fresh
            if (key := (_kind(e), e.key)) in held and held[key][0] != e.body_hash
        ),
        removed=tuple(f"{kind} {key!r}" for kind, key in removed),
        embedded=len(fresh),
    )


async def stored_entries(
    store: Store,
    connection: str,
) -> tuple[list[GlossaryTerm], list[Example]]:
    """Read back what the last load put in the store.

    Args:
        store: Store - The store.
        connection: str - Connection name.

    Returns:
        tuple[list[GlossaryTerm], list[Example]] - Terms and examples.

    """
    terms = [
        GlossaryTerm(term=t.term, definition=t.definition, table=t.table, sql=t.sql)
        for t in await store.knowledge.terms(connection)
    ]
    examples = [
        Example(question=e.question, sql=e.sql)
        for e in await store.knowledge.examples(connection)
    ]
    return terms, examples


def _kind(entry: GlossaryTerm | Example) -> str:
    """Name an entry's kind.

    Args:
        entry: GlossaryTerm | Example - The entry.

    Returns:
        str - `glossary` or `example`.

    """
    return "glossary" if isinstance(entry, GlossaryTerm) else "example"


def _stored_term(term: GlossaryTerm, model: str) -> StoredTerm:
    """Put a term in the store's form.

    Args:
        term: GlossaryTerm - The term.
        model: str - The model that embeds it.

    Returns:
        StoredTerm - The row.

    """
    return StoredTerm(
        term=term.term,
        definition=term.definition,
        table=term.table,
        sql=term.sql,
        body_hash=term.body_hash,
        model=model,
    )


def _stored_example(example: Example, model: str) -> StoredExample:
    """Put an example in the store's form.

    Args:
        example: Example - The example.
        model: str - The model that embeds it.

    Returns:
        StoredExample - The row.

    """
    return StoredExample(
        question=example.question,
        sql=example.sql,
        body_hash=example.body_hash,
        model=model,
    )
