"""What kind of call an audit record is about."""

from __future__ import annotations

from enum import StrEnum


class Action(StrEnum):
    """A call a caller can make, or a refusal to let it in; each leaves a record.

    The operator's approvals and rejections of proposed examples are recorded too:
    an approved example reaches every agent that searches.
    """

    SQL_RUN = "sql.run"
    SQL_CHECK = "sql.check"
    SCHEMA_SEARCH = "schema.search"
    SCHEMA_DESCRIBE = "schema.describe"
    RESOURCE_READ = "resource.read"
    ACCESS_DENIED = "access.denied"
    KNOWLEDGE_PROPOSE = "knowledge.propose"
    KNOWLEDGE_APPROVE = "knowledge.approve"
    KNOWLEDGE_REJECT = "knowledge.reject"
