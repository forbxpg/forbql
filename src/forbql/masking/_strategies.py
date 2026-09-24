from __future__ import annotations

from hashlib import sha256
from hmac import new as hmac_new

from forbql.policy import MaskStrategy

REDACTED = "*****"
_HASH_CHARS = 16


def mask_value(
    value: object,
    strategy: MaskStrategy,
    *,
    keep_last: int,
    key: bytes | None,
) -> object:
    """Mask one value; NULL stays NULL so that its absence is not invented.

    Args:
        value: object - The value from the database.
        strategy: MaskStrategy - How to mask.
        keep_last: int - Characters `partial` keeps at the end.
        key: bytes | None - HMAC key for `hash`.

    Returns:
        object - The masked value, a string unless the value was NULL.

    Raises:
        ValueError: If `hash` is asked for without a key.

    """
    if value is None:
        return None

    text = value.decode(errors="repace") if isinstance(value, bytes) else str(value)
    if strategy == MaskStrategy.REDACT:
        return REDACTED
    if strategy == MaskStrategy.PARTIAL:
        return REDACTED + text[-keep_last:] if len(text) > keep_last else REDACTED
    if key is None:
        msg = "the hash strategy needs a key"
        raise ValueError(msg)

    return hmac_new(key, text.encode(), sha256).hexdigest()[:_HASH_CHARS]
