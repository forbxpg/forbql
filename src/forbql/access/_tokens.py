"""Issuing tokens and turning a presented token into a principal."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from forbql.store import StoredGrant

from ._capability import Capability
from ._grant import Grant
from ._principal import Principal
from ._token import TokenParts

if TYPE_CHECKING:
    from collections.abc import Sequence

    from forbql.store import Store

DEFAULT_LIFETIME = timedelta(days=90)
MAX_LIFETIME = timedelta(days=365)


class AccessDeniedError(Exception):
    """A presented token opens nothing; the caller learns no more than that.

    Attributes:
        reason: str - Why, for the audit log only.

    """

    reason: str

    def __init__(self, reason: str) -> None:
        super().__init__("the token is not valid")
        self.reason = reason


@dataclass(frozen=True, slots=True)
class IssuedToken:
    """A token just issued: its value is shown once and kept nowhere.

    Attributes:
        value: str - `fql_<id>_<secret>`.
        token_id: str - The public id, for listing and revoking.
        expires_at: datetime - When it stops working.

    """

    value: str
    token_id: str
    expires_at: datetime


async def issue_token(
    store: Store,
    name: str,
    grants: Sequence[Grant],
    *,
    lifetime: timedelta = DEFAULT_LIFETIME,
) -> IssuedToken:
    """Issue a token with its grants; the store keeps only the secret's hash.

    Args:
        store: Store - The store.
        name: str - What the operator calls it; unique in the workspace.
        grants: Sequence[Grant] - What it may do; grants on one profile merge.
        lifetime: timedelta - Until it expires; mandatory, at most a year.

    Returns:
        IssuedToken - The token, to show once.

    Raises:
        ValueError: If there is no grant, or the lifetime is not within a year.

    """
    if not grants:
        msg = "a token needs a grant: without one it may do nothing"
        raise ValueError(msg)
    if not timedelta(0) < lifetime <= MAX_LIFETIME:
        msg = f"a token lives more than no time and at most {MAX_LIFETIME.days} days"
        raise ValueError(msg)
    merged: dict[tuple[str, str], set[Capability]] = {}
    for grant in grants:
        merged.setdefault((grant.connection, grant.profile), set()).update(
            grant.capabilities,
        )
    parts = TokenParts.new()
    expires_at = datetime.now(UTC) + lifetime
    await store.tokens.add(
        token_id=parts.token_id,
        name=name,
        secret_hash=parts.secret_hash(),
        expires_at=expires_at,
        grants=[
            StoredGrant(
                connection=connection,
                profile=profile,
                capabilities=tuple(sorted(capabilities)),
            )
            for (connection, profile), capabilities in sorted(merged.items())
        ],
    )
    return IssuedToken(
        value=parts.value,
        token_id=parts.token_id,
        expires_at=expires_at,
    )


async def authenticate(store: Store, presented: str) -> Principal:
    """Find who a presented token belongs to, checking it on every call.

    Nothing is cached: a revoked token stops working at once.

    Args:
        store: Store - The store.
        presented: str - What the caller sent.

    Returns:
        Principal - `token:<id>` with the token's grants.

    Raises:
        AccessDeniedError: If the token is malformed, unknown, wrong, revoked or
            expired; every case reads the same to the caller.

    """
    parts = TokenParts.parse(presented)
    if parts is None:
        reason = "not a forbql token"
        raise AccessDeniedError(reason)
    found = await store.tokens.find(parts.token_id)
    if found is None:
        reason = "unknown token"
        raise AccessDeniedError(reason)
    if not parts.matches(found.secret_hash):
        reason = "wrong secret"
        raise AccessDeniedError(reason)
    if found.revoked_at is not None:
        reason = "revoked"
        raise AccessDeniedError(reason)
    if datetime.now(UTC) >= found.expires_at:
        reason = "expired"
        raise AccessDeniedError(reason)
    return Principal(
        name=f"token:{found.token_id}",
        grants=tuple(
            Grant(
                connection=grant.connection,
                profile=grant.profile,
                capabilities=frozenset(Capability(name) for name in grant.capabilities),
            )
            for grant in found.grants
        ),
    )
