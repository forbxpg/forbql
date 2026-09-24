from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

GENESIS = "0" * 64
"""The genesis block hash."""


class AuditRecord(BaseModel):
    """What happened on one call, allowed or not."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    at: datetime = Field(description="When the call finished, UTC.")
    principal: str = Field(description="Who called.")
    connection: str = Field(description="Connection name.")
    profile: str = Field(description="Profile name.")
    policy_hash: str = Field(description="Hash of the policy the verdict came from.")
    sql: str = Field(description="The SQL the caller sent.")
    executed_sql: str | None = Field(
        description="The SQL that ran; None when rejected.",
    )
    allowed: bool = Field(description="Whether the firewall allowed it.")
    rules: tuple[str, ...] = Field(description="Rules that rejected it.")
    rows: int = Field(description="Rows returned.")
    size: int = Field(description="Bytes returned.")
    truncated: bool = Field(description="Whether a cap cut the result.")
    duration_ms: int = Field(description="Wall time of the call.")
    error_class: str | None = Field(description="Database failure class, if any.")
    error_detail: str | None = Field(description="The database's own message, if any.")
    previous: str = Field(
        description="Hash of the record before; GENESIS for the first.",
    )
    hash: str = Field(description="Hash of this record without this field.")

    def expected_hash(self) -> str:
        """Hash the record's content, everything but `hash` itself.

        Returns:
            str - Hex SHA-256 of canonical JSON.

        """
        content = self.model_dump(mode="json", exclude={"hash"})
        canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()
