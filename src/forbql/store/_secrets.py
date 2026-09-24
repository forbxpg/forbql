"""Sealing DSNs with AES-256-GCM under a master key the store never holds."""

from __future__ import annotations

import binascii
import secrets
from base64 import b64decode
from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ._errors import StoreError

if TYPE_CHECKING:
    from pathlib import Path

_KEY_BYTES = 32
_NONCE_BYTES = 12
_KEY_ID_CHARS = 16


@dataclass(frozen=True, slots=True)
class Sealed:
    """A secret as the store keeps it.

    Attributes:
        key_id: str - Which key sealed it, so a rotated key can be told apart.
        blob: bytes - The nonce, then the ciphertext with its tag.

    """

    key_id: str
    blob: bytes


class SecretKey:
    """The master key: seals and opens secrets bound to where they are stored.

    Args:
        raw: bytes - 32 random bytes.

    Raises:
        StoreError: If the key is not 32 bytes.

    """

    key_id: str
    _cipher: AESGCM

    def __init__(self, raw: bytes) -> None:
        if len(raw) != _KEY_BYTES:
            msg = f"the secret key must be {_KEY_BYTES} bytes, base64url-encoded"
            raise StoreError(msg)
        self._cipher = AESGCM(raw)
        self.key_id = sha256(raw).hexdigest()[:_KEY_ID_CHARS]

    @classmethod
    def load(cls, value: str | None, file: Path | None) -> SecretKey:
        """Read the key from its variable, else from its file: no key, no start.

        Args:
            value: str | None - `FORBQL_SECRET_KEY`.
            file: Path | None - `FORBQL_SECRET_KEY_FILE`.

        Returns:
            SecretKey - The key.

        Raises:
            StoreError: If neither is set, or the text is not a base64url key.

        """
        if value is not None:
            text = value
        elif file is not None:
            text = file.read_text(encoding="utf-8").strip()
        else:
            msg = (
                "set FORBQL_SECRET_KEY or FORBQL_SECRET_KEY_FILE: the store seals DSNs"
            )
            raise StoreError(msg)
        try:
            padded = text + "=" * (-len(text) % 4)
            raw = b64decode(padded, altchars=b"-_", validate=True)
        except (binascii.Error, ValueError) as error:
            msg = "the secret key is not base64url"
            raise StoreError(msg) from error
        return cls(raw)

    @staticmethod
    def generate() -> str:
        """Make a new key.

        Returns:
            str - 32 random bytes, base64url-encoded.

        """
        return secrets.token_urlsafe(_KEY_BYTES)

    def seal(self, secret: str, *, context: str) -> Sealed:
        """Encrypt a secret, binding it to where it will be stored.

        Args:
            secret: str - The plain text.
            context: str - Where it lives, such as `default/bank/analyst`; opening
                it anywhere else fails.

        Returns:
            Sealed - The key id and the sealed bytes.

        """
        nonce = secrets.token_bytes(_NONCE_BYTES)
        sealed = self._cipher.encrypt(nonce, secret.encode(), context.encode())
        return Sealed(key_id=self.key_id, blob=nonce + sealed)

    def open(self, sealed: Sealed, *, context: str) -> str:
        """Decrypt a secret sealed for this context with this key.

        Args:
            sealed: Sealed - What the store keeps.
            context: str - Where it was read from.

        Returns:
            str - The plain text.

        Raises:
            StoreError: If another key sealed it, or it was changed or moved.

        """
        if sealed.key_id != self.key_id:
            msg = f"sealed with key {sealed.key_id}; the current key is {self.key_id}"
            raise StoreError(msg)
        nonce, body = sealed.blob[:_NONCE_BYTES], sealed.blob[_NONCE_BYTES:]
        try:
            return self._cipher.decrypt(nonce, body, context.encode()).decode()
        except InvalidTag as error:
            msg = "the secret does not open: it was changed or moved"
            raise StoreError(msg) from error
