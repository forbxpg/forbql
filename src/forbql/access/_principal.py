"""Who asks: every request has a principal, and a principal has only its grants."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._capability import Capability
    from ._grant import Grant


@dataclass(frozen=True, slots=True)
class Principal:
    """A caller and what its grants allow; without a grant it may do nothing.

    Attributes:
        name: str - As the audit log records it, such as `token:1a2b3c4d5e6f`.
        grants: tuple[Grant, ...] - What it may do.

    """

    name: str
    grants: tuple[Grant, ...] = ()

    def may(self, capability: Capability, *, connection: str, profile: str) -> bool:
        """Tell whether a grant allows this capability on this profile.

        Args:
            capability: Capability - What the caller wants to do.
            connection: str - Connection name.
            profile: str - Profile name.

        Returns:
            bool - True only when one grant names all three.

        """
        return any(
            grant.connection == connection
            and grant.profile == profile
            and capability in grant.capabilities
            for grant in self.grants
        )
