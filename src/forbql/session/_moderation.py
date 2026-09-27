"""The operator's side of proposed examples: list, approve, reject."""

from __future__ import annotations

from asyncio import to_thread
from contextlib import AsyncExitStack
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING

from forbql.audit import Action
from forbql.knowledge import Example, reach
from forbql.policy import Policy, load_policy, policy_hash
from forbql.store import ProposalError, StoredExample

from ._config import ForbqlSettings, SessionError
from ._knowledge import default_embedder
from ._store import open_store

if TYPE_CHECKING:
    from pathlib import Path

    from forbql.knowledge import Embedder, Reach
    from forbql.store import Store, StoredProposal


@dataclass(frozen=True, slots=True)
class Approval:
    """What approving a proposal did.

    Attributes:
        proposal: StoredProposal - The proposal, as it was waiting.
        reach: Reach - Which profiles search shows it to, and why not the others.

    """

    proposal: StoredProposal
    reach: Reach


async def proposals(
    *,
    connection: str | None = None,
    approved: bool = False,
) -> list[StoredProposal]:
    """List the proposals waiting for review, or the approved ones.

    Args:
        connection: str | None - Only this connection's; None for every one.
        approved: bool - Approved ones instead of those waiting.

    Returns:
        list[StoredProposal] - Oldest first.

    """
    async with AsyncExitStack() as stack:
        store = await _store(stack)
        return await store.proposals.listed(connection=connection, approved=approved)


async def approve_example(
    policy: Policy | str | Path,
    number: int,
    *,
    by: str,
    embedder: Embedder | None = None,
) -> Approval:
    """Check a waiting proposal again, then add it to the examples search shows.

    Its proposer's profile must still see it: the policy or the schema may have
    changed since it was proposed.

    Args:
        policy: Policy | str | Path - The policy, or the path to its file.
        number: int - The proposal's number.
        by: str - Who approves it, as the audit records it.
        embedder: Embedder | None - The model the search index is built with.

    Returns:
        Approval - The proposal and who sees it.

    Raises:
        SessionError: If there is no store or synced schema, no such proposal is
            waiting, its profile may not see it now, or its question became an
            example.

    """
    start = monotonic()
    loaded = policy if isinstance(policy, Policy) else load_policy(policy)
    async with AsyncExitStack() as stack:
        store = await _store(stack)
        proposal = await store.proposals.get(number)
        if proposal is None or proposal.approved_at is not None:
            msg = f"no proposal {number} is waiting for review"
            raise SessionError(msg)
        synced = await store.snapshots.latest(proposal.connection)
        if synced is None:
            msg = f"no synced schema of {proposal.connection} to check it against"
            raise SessionError(msg)
        example = Example(question=proposal.question, sql=proposal.sql)
        [found] = reach(
            [example],
            policy=loaded,
            connection=proposal.connection,
            catalog=synced.catalog,
        )
        if proposal.profile not in found.seen:
            why = found.hidden.get(proposal.profile, "it is gone from the policy")
            msg = f"{proposal.profile}, who proposed it, may not see it now: {why}"
            raise SessionError(msg)
        model = embedder or default_embedder()
        [vector] = await to_thread(model.documents, [example.body])
        stored = StoredExample(
            question=example.question,
            sql=example.sql,
            body_hash=example.body_hash,
            model=model.name,
        )
        try:
            await store.proposals.approve(number, by=by, example=stored, vector=vector)
        except ProposalError as err:
            raise SessionError(str(err)) from err
        await _decided(
            store,
            proposal,
            policy=loaded,
            action=Action.KNOWLEDGE_APPROVE,
            by=by,
            start=start,
        )
    return Approval(proposal=proposal, reach=found)


async def reject_example(
    policy: Policy | str | Path,
    number: int,
    *,
    by: str,
) -> StoredProposal:
    """Drop a proposal; an approved one leaves search with it.

    Args:
        policy: Policy | str | Path - The policy, or the path to its file; the audit
            record names it.
        number: int - The proposal's number.
        by: str - Who rejects it, as the audit records it.

    Returns:
        StoredProposal - The proposal as it was.

    Raises:
        SessionError: If there is no store or no such proposal.

    """
    start = monotonic()
    loaded = policy if isinstance(policy, Policy) else load_policy(policy)
    async with AsyncExitStack() as stack:
        store = await _store(stack)
        proposal = await store.proposals.reject(number)
        if proposal is None:
            msg = f"there is no proposal {number}"
            raise SessionError(msg)
        await _decided(
            store,
            proposal,
            policy=loaded,
            action=Action.KNOWLEDGE_REJECT,
            by=by,
            start=start,
        )
    return proposal


async def _store(stack: AsyncExitStack) -> Store:
    """Open the store, or refuse: proposals live nowhere else.

    Args:
        stack: AsyncExitStack - Closes the store when the caller is done.

    Returns:
        Store - The store.

    Raises:
        SessionError: If `FORBQL_STORE_DSN` is not set or the store refuses.

    """
    store = await open_store(stack, ForbqlSettings())
    if store is None:
        msg = "proposals live in the store: set FORBQL_STORE_DSN"
        raise SessionError(msg)
    return store


async def _decided(  # ruff: ignore[too-many-arguments] - the decision and its context
    store: Store,
    proposal: StoredProposal,
    *,
    policy: Policy,
    action: Action,
    by: str,
    start: float,
) -> None:
    """Record the operator's decision in the audit chain.

    Args:
        store: Store - The store, whose chain it goes to.
        policy: Policy - The policy it was decided under.
        proposal: StoredProposal - The proposal.
        action: Action - Approval or rejection.
        by: str - Who decided.
        start: float - When the decision began, on the monotonic clock.

    """
    _ = await store.audit.append(
        principal=by,
        connection=proposal.connection,
        profile=proposal.profile,
        action=action,
        policy_hash=policy_hash(policy),
        sql=proposal.sql,
        executed_sql=None,
        allowed=True,
        rules=(),
        rows=0,
        size=0,
        truncated=False,
        duration_ms=round((monotonic() - start) * 1000),
        error_class=None,
        error_detail=None,
    )
