"""Letting a token in to one profile of one connection, and recording who was not."""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from forbql.access import AccessDeniedError, Capability, TokenParts, authenticate
from forbql.audit import Action
from forbql.policy import policy_hash

from ._config import ForbqlSettings, SessionError
from ._store import open_store

if TYPE_CHECKING:
    from types import TracebackType

    from forbql.policy import Policy
    from forbql.store import Store

_log = logging.getLogger(__name__)

_UNKNOWN = "unknown token"
"""The one reason an id the store does not hold is refused for."""


@dataclass(frozen=True, slots=True)
class Admission:
    """A token let in: who it is and what it may do here.

    Attributes:
        principal: str - `token:<id>`, as the audit log records it.
        capabilities: frozenset[Capability] - What its grants allow on this
            profile; empty when it has none, and every call is then refused.

    """

    principal: str
    capabilities: frozenset[Capability]


class Gate:
    """Checks tokens for one profile of one connection, against the store.

    Refusals of a token the store knows (revoked, expired, a wrong secret, no grant
    here, a capability it lacks) are audited; anything else is only logged, so a
    caller without a token cannot grow the audit chain or hold its head.

    Args:
        policy: Policy - The policy, whose hash refusal records carry.
        connection: str - Connection name.
        profile: str - Profile name.

    """

    _policy_hash: str
    _connection: str
    _profile: str
    _stack: AsyncExitStack
    _store: Store | None

    def __init__(self, policy: Policy, *, connection: str, profile: str) -> None:
        self._policy_hash = policy_hash(policy)
        self._connection = connection
        self._profile = profile
        self._stack = AsyncExitStack()
        self._store = None

    async def __aenter__(self) -> Self:
        """Open the store the tokens live in.

        Returns:
            Self - The gate.

        Raises:
            SessionError: If no store is configured, or it refuses.

        """
        self._store = await open_store(self._stack, ForbqlSettings())
        if self._store is None:
            await self._stack.aclose()
            msg = "tokens live in the store: set FORBQL_STORE_DSN"
            raise SessionError(msg)
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        """Close the store.

        Args:
            kind: type[BaseException] | None - The exception's type, if any.
            error: BaseException | None - The exception, if any.
            trace: TracebackType | None - Its traceback, if any.

        """
        await self._stack.aclose()

    async def admit(self, presented: str) -> Admission | None:
        """Check a presented token; nothing is cached, so revocation is immediate.

        Args:
            presented: str - What the caller sent as its bearer token.

        Returns:
            Admission | None - Who it is and what it may do here; None when the
                token opens nothing.

        """
        try:
            principal = await authenticate(self._opened(), presented)
        except AccessDeniedError as err:
            parts = TokenParts.parse(presented)
            if parts is None or err.reason == _UNKNOWN:
                _log.warning("refused a request: %s", err.reason)
            else:
                await self.refuse(f"token:{parts.token_id}", "authenticate", err.reason)
            return None
        allowed = frozenset(
            capability
            for capability in Capability
            if principal.may(
                capability,
                connection=self._connection,
                profile=self._profile,
            )
        )
        if not allowed:
            await self.refuse(principal.name, "authenticate", "no grant")
        return Admission(principal=principal.name, capabilities=allowed)

    async def refuse(self, principal: str, asked: str, reason: str) -> None:
        """Record a refusal of a caller the store knows.

        Args:
            principal: str - `token:<id>`.
            asked: str - What it tried: `authenticate`, or a tool or resource.
            reason: str - Why it was refused.

        """
        _ = await self._opened().audit.append(
            principal=principal,
            connection=self._connection,
            profile=self._profile,
            action=Action.ACCESS_DENIED,
            policy_hash=self._policy_hash,
            sql=asked,
            executed_sql=None,
            allowed=False,
            rules=(),
            rows=0,
            size=0,
            truncated=False,
            duration_ms=0,
            error_class=reason,
            error_detail=None,
        )

    def _opened(self) -> Store:
        """Return the store, which is open inside the gate's `async with`.

        Returns:
            Store - The store.

        Raises:
            SessionError: If the gate is used outside its `async with`.

        """
        if self._store is None:
            msg = "the gate is not open"
            raise SessionError(msg)
        return self._store
