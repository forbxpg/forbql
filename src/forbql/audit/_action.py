"""What kind of call an audit record is about."""

from __future__ import annotations

from enum import StrEnum


class Action(StrEnum):
    """A call a caller can make; every one of them leaves a record."""

    SQL_RUN = "sql.run"
    SQL_CHECK = "sql.check"
    SCHEMA_SEARCH = "schema.search"
    SCHEMA_DESCRIBE = "schema.describe"
    RESOURCE_READ = "resource.read"
