"""A grant binds a principal to one profile of one connection, with capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from ._capability import Capability

_PARTS = 3


@dataclass(frozen=True, slots=True)
class Grant:
    """What a principal may do with one profile of one connection.

    Attributes:
        connection: str - Connection name, as in the policy.
        profile: str - Profile name.
        capabilities: frozenset[Capability] - What it may do there.

    """

    connection: str
    profile: str
    capabilities: frozenset[Capability]

    @classmethod
    def parse(cls, text: str) -> Self:
        """Read a grant written as `connection:profile:capability[,capability]`.

        Args:
            text: str - Such as `bank:analyst:sql.check,sql.run`.

        Returns:
            Self - The grant.

        Raises:
            ValueError: If the text has another shape or names an unknown capability.

        """
        parts = text.split(":")
        if len(parts) != _PARTS or not all(parts):
            msg = f"a grant is connection:profile:capability[,capability], not {text!r}"
            raise ValueError(msg)
        connection, profile, names = parts
        known = {capability.value for capability in Capability}
        if unknown := sorted({name.strip() for name in names.split(",")} - known):
            choices = ", ".join(sorted(known))
            msg = f"unknown capability {', '.join(unknown)}; choose from {choices}"
            raise ValueError(msg)
        capabilities = frozenset(Capability(name.strip()) for name in names.split(","))
        return cls(connection=connection, profile=profile, capabilities=capabilities)
