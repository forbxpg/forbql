"""Where a session's audit records go: a file, or the store."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._record import AuditRecord


class AuditSink(ABC):
    """Appends chained records; each sink keeps one chain."""

    @abstractmethod
    async def append(self, **fields: object) -> AuditRecord:
        """Write one record after the last one of the chain.

        Args:
            **fields: object - `AuditRecord` fields other than `at`, `previous`, `hash`.

        Returns:
            AuditRecord - The record as written.

        """
