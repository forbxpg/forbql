"""Read-only execution on SQLite, PostgreSQL and MySQL."""

from __future__ import annotations

from ._connect import connect
from ._errors import ErrorClass, QueryError
from ._privileges import PrivilegeReport
from ._protocol import QueryEngine, Restriction
from ._result import Collector, ResultSet

__all__ = (
    "Collector",
    "ErrorClass",
    "PrivilegeReport",
    "QueryEngine",
    "QueryError",
    "Restriction",
    "ResultSet",
    "connect",
)
