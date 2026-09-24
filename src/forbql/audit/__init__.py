"""The audit log: one record per call, each chained to the one before by its hash."""

from __future__ import annotations

from ._log import AuditLog, Verification, verify_chain, verify_log
from ._record import GENESIS, AuditRecord
from ._sink import AuditSink

__all__ = (
    "GENESIS",
    "AuditLog",
    "AuditRecord",
    "AuditSink",
    "Verification",
    "verify_chain",
    "verify_log",
)
