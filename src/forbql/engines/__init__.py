"""Read-only execution on SQLite, PostgreSQL and MySQL."""

from __future__ import annotations

from ._errors import ErrorClass, QueryError
from ._protocol import QueryEngine, Restriction
from ._result import Collector, ResultSet

__all__ = (
    "Collector",
    "ErrorClass",
    "QueryEngine",
    "QueryError",
    "Restriction",
    "ResultSet",
)
