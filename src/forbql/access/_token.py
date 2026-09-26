"""Tokens `fql_<id>_<secret>`: the id finds the row, the secret is never stored."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from hashlib import sha256
from hmac import compare_digest
from typing import Self

_ID_BYTES = 6
_SECRET_BYTES = 32
_TOKEN = re.compile(r"fql_(?P<id>[0-9a-f]{12})_(?P<secret>[A-Za-z0-9_-]{43})")
"""The prefix lets secret scanners recognise a leaked token."""


@dataclass(frozen=True, slots=True)
class TokenParts:
    """A token split into its public id and its secret.

    Attributes:
        token_id: str - 12 hex characters; stored, shown in listings.
        secret: str - 256 random bits, base64url; only its hash is stored.

    """

    token_id: str
    secret: str

    @classmethod
    def new(cls) -> Self:
        """Make a token from fresh randomness.

        Returns:
            Self - The token.

        """
        return cls(
            token_id=secrets.token_hex(_ID_BYTES),
            secret=secrets.token_urlsafe(_SECRET_BYTES),
        )

    @classmethod
    def parse(cls, text: str) -> Self | None:
        """Split a presented token; anything else is not one.

        Args:
            text: str - What the caller sent.

        Returns:
            Self | None - The parts; None when the text is not a token.

        """
        found = _TOKEN.fullmatch(text)
        if found is None:
            return None
        return cls(token_id=found["id"], secret=found["secret"])

    @property
    def value(self) -> str:
        """The token as the caller holds it: shown once, never stored."""
        return f"fql_{self.token_id}_{self.secret}"

    def secret_hash(self) -> str:
        """Hash the secret for the store; 256 random bits need no slow hash.

        Returns:
            str - Hex SHA-256.

        """
        return sha256(self.secret.encode()).hexdigest()

    def matches(self, stored_hash: str) -> bool:
        """Compare with the stored hash in constant time.

        Args:
            stored_hash: str - What the store keeps.

        Returns:
            bool - Whether the secret is the one issued.

        """
        return compare_digest(self.secret_hash(), stored_hash)
