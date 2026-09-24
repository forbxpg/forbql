"""forbql's own state in its own PostgreSQL: sealed DSNs, the audit chain."""

from __future__ import annotations

from ._errors import StoreError
from ._migrate import check_revision, head, migrate
from ._secrets import Sealed, SecretKey
from ._store import Store, StoredConnection

__all__ = (
    "Sealed",
    "SecretKey",
    "Store",
    "StoreError",
    "StoredConnection",
    "check_revision",
    "head",
    "migrate",
)
