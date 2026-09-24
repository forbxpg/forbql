"""What goes wrong with the service store."""

from __future__ import annotations


class StoreError(Exception):
    """The store cannot serve: no key, a wrong key, an old schema, no connection."""
