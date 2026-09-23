"""Base model shared by every policy section."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class PolicyModel(BaseModel):
    """Immutable model that rejects unknown keys, so a typo never passes silently."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")
