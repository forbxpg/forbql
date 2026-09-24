"""Database errors as the caller sees them: a class and a hint, never the raw text."""

from __future__ import annotations

from enum import StrEnum


class ErrorClass(StrEnum):
    """Kind of database failure; the database's own message goes to the audit log."""

    TIMEOUT = "timeout"
    PERMISSION_DENIED = "permission_denied"
    READ_ONLY = "read_only"
    INVALID_QUERY = "invalid_query"
    CONNECTION = "connection"
    DATABASE = "database"


_HINTS = {
    ErrorClass.TIMEOUT: "the query ran past the profile's time limit; narrow it",
    ErrorClass.PERMISSION_DENIED: "the database role may not read this",
    ErrorClass.READ_ONLY: "forbql runs read-only transactions",
    ErrorClass.INVALID_QUERY: "the database rejected the query; check names and types",
    ErrorClass.CONNECTION: "the database is unreachable; try again later",
    ErrorClass.DATABASE: "the database could not run the query",
}


class QueryError(Exception):
    """A query failed inside the database.

    Attributes:
        error_class: ErrorClass - What kind of failure it was.
        detail: str - The database's own message, for the audit log.

    """

    error_class: ErrorClass
    detail: str

    def __init__(self, error_class: ErrorClass, detail: str) -> None:
        super().__init__(f"{error_class}: {detail}")
        self.error_class = error_class
        self.detail = detail

    @property
    def hint(self) -> str:
        """What the caller can do about it, without database internals."""
        return _HINTS[self.error_class]
