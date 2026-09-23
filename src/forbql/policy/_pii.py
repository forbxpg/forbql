"""PII classes and masking strategies for columns listed in a profile."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from ._model import PolicyModel


class PiiClass(StrEnum):
    """How a PII column may appear in a query."""

    MASK = "mask"
    AGGREGATE_ONLY = "aggregate_only"
    DENY = "deny"


class MaskStrategy(StrEnum):
    """How a masked column is rewritten on output."""

    REDACT = "redact"
    PARTIAL = "partial"
    HASH = "hash"


class PiiRule(PolicyModel):
    """PII class of one column and, for masked columns, the masking strategy.

    Attributes:
        pii_class: PiiClass - Where the column may appear; `class` in YAML.
        strategy: MaskStrategy | None - Output masking; set for `mask` only.
        keep_last: int - Characters kept at the end by the `partial` strategy.

    """

    pii_class: PiiClass = Field(alias="class")
    strategy: MaskStrategy | None = None
    keep_last: int = Field(default=4, ge=1, le=16)

    @model_validator(mode="after")
    def _check_strategy(self) -> Self:
        """Tie `strategy` and `keep_last` to the class they make sense for.

        Returns:
            Self - The validated rule.

        Raises:
            ValueError: If a strategy is missing for `mask` or given for another class,
                or `keep_last` is set without the `partial` strategy.

        """
        if self.pii_class is PiiClass.MASK and self.strategy is None:
            msg = "class 'mask' requires a strategy: redact, partial or hash"
            raise ValueError(msg)
        if self.pii_class is not PiiClass.MASK and self.strategy is not None:
            msg = f"class '{self.pii_class}' takes no strategy; only 'mask' does"
            raise ValueError(msg)
        if (
            "keep_last" in self.model_fields_set
            and self.strategy is not MaskStrategy.PARTIAL
        ):
            msg = "keep_last applies only to the 'partial' strategy"
            raise ValueError(msg)
        return self
