"""What a principal may do with a profile."""

from __future__ import annotations

from enum import StrEnum


class Capability(StrEnum):
    """One thing a grant allows; part of the public API."""

    SCHEMA_READ = "schema.read"
    SQL_CHECK = "sql.check"
    SQL_RUN = "sql.run"
    KNOWLEDGE_PROPOSE = "knowledge.propose"
