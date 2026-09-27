"""Loading a connection's knowledge file into the store."""

from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import TYPE_CHECKING

from forbql.knowledge import (
    KnowledgeError,
    index_knowledge,
    load_knowledge,
    reach,
    resolved,
)
from forbql.policy import Policy, load_policy
from forbql.store import StoreError

from ._config import ForbqlSettings, SessionError
from ._knowledge import default_embedder
from ._store import open_store

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from forbql.knowledge import Embedder, Example, KnowledgeChange, Reach
    from forbql.store import Store


@dataclass(frozen=True, slots=True)
class KnowledgeSync:
    """What a knowledge sync did.

    Attributes:
        change: KnowledgeChange - What the store took in.
        reach: tuple[Reach, ...] - Who sees each entry.

    """

    change: KnowledgeChange
    reach: tuple[Reach, ...]


async def sync_knowledge(
    policy: Policy | str | Path,
    *,
    connection: str,
    path: str | Path,
    embedder: Embedder | None = None,
) -> KnowledgeSync:
    """Make the store hold exactly what the knowledge file says, or nothing new.

    Every entry is checked under every profile against the synced schema; an entry
    no profile may see is an error, and one error keeps the store as it was.

    Args:
        policy: Policy | str | Path - The policy, or the path to its file.
        connection: str - Connection name.
        path: str | Path - The knowledge file.
        embedder: Embedder | None - The model for search.

    Returns:
        KnowledgeSync - What changed, and who sees what.

    Raises:
        SessionError: If the file is broken, there is no store or synced schema, an
            entry reaches no profile, or the store refuses.

    """
    loaded = policy if isinstance(policy, Policy) else load_policy(policy)
    _ = loaded.connection(connection)
    async with AsyncExitStack() as stack:
        store = await open_store(stack, ForbqlSettings())
        if store is None:
            msg = "knowledge lives in the store: set FORBQL_STORE_DSN"
            raise SessionError(msg)
        synced = await store.snapshots.latest(connection)
        if synced is None:
            sync = f"run `forbql schema sync {connection}`"
            msg = f"no synced schema of {connection} to check knowledge against: {sync}"
            raise SessionError(msg)
        try:
            terms, examples = resolved(load_knowledge(path), synced.catalog)
            await _refuse_approved(store, connection, examples)
            found = reach(
                [*terms, *examples],
                policy=loaded,
                connection=connection,
                catalog=synced.catalog,
            )
        except KnowledgeError as err:
            raise SessionError(str(err)) from err
        if unseen := [r for r in found if not r.seen]:
            lines = [
                f"  {r.label}: {profile}: {why}"
                for r in unseen
                for profile, why in r.hidden.items()
            ]
            msg = "no profile may see these entries:\n" + "\n".join(lines)
            raise SessionError(msg)
        try:
            change = await index_knowledge(
                store,
                embedder or default_embedder(),
                connection,
                terms,
                examples,
            )
        except StoreError as err:
            msg = f"the store refused: {err}"
            raise SessionError(msg) from err
    return KnowledgeSync(change=change, reach=tuple(found))


async def _refuse_approved(
    store: Store,
    connection: str,
    examples: Sequence[Example],
) -> None:
    """Refuse file examples that repeat an approved proposal's question.

    Args:
        store: Store - The store.
        connection: str - Connection name.
        examples: Sequence[Example] - The file's examples.

    Raises:
        KnowledgeError: Naming each proposal the file repeats.

    """
    approved = {
        e.question: e.proposal
        for e in await store.knowledge.examples(connection)
        if e.proposal is not None
    }
    if repeated := [
        f"  example {e.question!r} is approved proposal {approved[e.question]}"
        for e in examples
        if e.question in approved
    ]:
        fix = "drop them from the file, or reject them with `forbql examples reject`"
        msg = f"the knowledge file repeats approved proposals; {fix}:\n" + "\n".join(
            repeated,
        )
        raise KnowledgeError(msg)
