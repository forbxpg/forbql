"""The SQL firewall: checks a query against a policy and a schema snapshot."""

from __future__ import annotations

from ._firewall import Firewall, check_structure
from ._rule_id import RuleId
from ._snapshot import SchemaSnapshot
from ._verdict import ColumnMask, Span, Verdict, Violation

__all__ = (
    "ColumnMask",
    "Firewall",
    "RuleId",
    "SchemaSnapshot",
    "Span",
    "Verdict",
    "Violation",
    "check_structure",
)
