"""The policy file: schema version, connections and their profiles."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from ._engine import Engine
from ._errors import UnknownProfileError
from ._model import PolicyModel
from ._profile import Profile

type Name = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,62}$")]


class Connection(PolicyModel):
    """Profiles of one database; its DSN lives in the store, never in the policy.

    Attributes:
        engine: Engine - Engine of the database; selects the dialect rules.
        profiles: dict[str, Profile] - Profiles by name.

    """

    engine: Engine
    profiles: dict[Name, Profile] = Field(min_length=1)


class Policy(PolicyModel):
    """Security policy v1, the source of truth versioned in the user's git repository.

    Attributes:
        version: Literal[1] - Schema version.
        connections: dict[str, Connection] - Connections by name.

    """

    version: Literal[1]
    connections: dict[Name, Connection] = Field(min_length=1)

    def connection(self, name: str) -> Connection:
        """Return a connection by name.

        Args:
            name: str - Connection name.

        Returns:
            Connection - The connection.

        Raises:
            UnknownProfileError: If the policy has no such connection.

        """
        try:
            return self.connections[name]
        except KeyError:
            msg = f"connection '{name}' is not in the policy"
            raise UnknownProfileError(msg) from None

    def profile(self, connection: str, profile: str) -> Profile:
        """Return a profile of a connection.

        Args:
            connection: str - Connection name.
            profile: str - Profile name.

        Returns:
            Profile - The profile.

        Raises:
            UnknownProfileError: If the connection or its profile is not in the policy.

        """
        try:
            return self.connection(connection).profiles[profile]
        except KeyError:
            msg = f"profile '{profile}' is not in connection '{connection}'"
            raise UnknownProfileError(msg) from None
