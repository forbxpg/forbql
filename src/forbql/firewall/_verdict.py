"""The firewall's answer: allowed or not, why, and the SQL that may run."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel, ConfigDict

from forbql.policy import MaskStrategy

from ._rule_id import RuleId

if TYPE_CHECKING:
    from sqlglot import exp


class _Frozen(BaseModel):
    """Immutable model."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)


class Span(_Frozen):
    """Characters of the original SQL a violation points at.

    Attributes:
        start: int - Offset of the first character.
        end: int - Offset after the last character.

    """

    start: int
    end: int

    @classmethod
    def of(cls, node: exp.Expr) -> Span | None:
        """Return the span sqlglot recorded for a node, if it recorded one.

        Args:
            node: exp.Expr - A node of the parsed tree.

        Returns:
            Span | None - The span, or None when the node carries no position.

        """
        meta = node.meta
        start, end = meta.get("start"), meta.get("end")
        if isinstance(start, int) and isinstance(end, int):
            return cls(start=start, end=end + 1)
        return None


class Violation(_Frozen):
    """One reason a query was rejected.

    Attributes:
        rule: RuleId - The rule.
        message: str - What is wrong, naming only what the profile can see.
        hint: str | None - How to fix it, built only from what the profile can see.
        span: Span | None - Where in the original SQL, when known.

    """

    rule: RuleId
    message: str
    hint: str | None = None
    span: Span | None = None


class ColumnMask(_Frozen):
    """Masking to apply to one output column.

    Attributes:
        position: int - Zero-based position of the output column.
        column: str - Source column as `schema.table.column`.
        strategy: MaskStrategy - How to mask.
        keep_last: int - Characters kept by the `partial` strategy.

    """

    position: int
    column: str
    strategy: MaskStrategy
    keep_last: int


class Verdict(_Frozen):
    """Result of a firewall check.

    Attributes:
        allowed: bool - Whether the query may run.
        sql: str | None - SQL regenerated from the checked tree; None when rejected.
        violations: tuple[Violation, ...] - Why the query was rejected.
        rewrites: tuple[str, ...] - What the firewall changed, such as an added LIMIT.
        masks: tuple[ColumnMask, ...] - Output columns to mask.
        structural_only: bool - True when no schema snapshot was available, so tables,
            columns and PII were not checked.
        policy_hash: str | None - Hash of the policy used; None without a policy.

    """

    allowed: bool
    sql: str | None
    violations: tuple[Violation, ...] = ()
    rewrites: tuple[str, ...] = ()
    masks: tuple[ColumnMask, ...] = ()
    structural_only: bool
    policy_hash: str | None
