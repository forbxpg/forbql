"""A profile: what one kind of caller may see and how far its queries may go."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from ._model import PolicyModel
from ._pii import PiiRule

type Identifier = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_$]{0,63}$"),
]
type TableName = Annotated[
    str,
    StringConstraints(
        pattern=r"^[A-Za-z_][A-Za-z0-9_$]{0,63}\.[A-Za-z_][A-Za-z0-9_$]{0,63}$",
    ),
]


class Limits(PolicyModel):
    """Bounds on one request; the engines enforce the byte and time limits.

    Attributes:
        max_rows: int - Rows returned at most; the firewall enforces it with LIMIT.
        max_result_bytes: int - Bytes of the whole result at most.
        max_cell_bytes: int - Bytes of one cell at most; longer cells are truncated.
        statement_timeout_ms: int - Server-side statement timeout.
        max_joins: int - JOIN clauses in the whole query at most.
        max_subquery_depth: int - Nesting depth of SELECTs at most; the outer one is 0.

    """

    max_rows: int = Field(default=1000, ge=1)
    max_result_bytes: int = Field(default=5_000_000, ge=1)
    max_cell_bytes: int = Field(default=10_000, ge=1)
    statement_timeout_ms: int = Field(default=5_000, ge=1)
    max_joins: int = Field(default=6, ge=0)
    max_subquery_depth: int = Field(default=4, ge=0)


class ExplainThresholds(PolicyModel):
    """Planner cost thresholds for PostgreSQL and MySQL; advisory, not a hard bound.

    Attributes:
        confirm_cost: float - From this cost on, a query needs confirmation.
        block_cost: float - From this cost on, a query is blocked.

    """

    confirm_cost: float = Field(default=1.0e6, gt=0)
    block_cost: float = Field(default=1.0e8, gt=0)

    @model_validator(mode="after")
    def _check_order(self) -> Self:
        """Keep the confirmation threshold below the blocking one.

        Returns:
            Self - The validated thresholds.

        Raises:
            ValueError: If `confirm_cost` is not below `block_cost`.

        """
        if self.confirm_cost >= self.block_cost:
            msg = "confirm_cost must be below block_cost"
            raise ValueError(msg)
        return self


class TableAccess(PolicyModel):
    """Columns of one table visible to a profile.

    Attributes:
        columns: Literal["*"] | tuple[str, ...] - Visible columns; `*` means all.
        pii: dict[str, PiiRule] - PII class per column.
        samples: tuple[str, ...] - Columns `describe_table` may show values of.

    """

    columns: Literal["*"] | tuple[Identifier, ...]
    pii: dict[Identifier, PiiRule] = Field(default_factory=dict)
    samples: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def _check_columns(self) -> Self:
        """Keep `pii` and `samples` within the listed columns, and samples free of PII.

        Returns:
            Self - The validated table access.

        Raises:
            ValueError: If the column list is empty or repeats a name, `pii` or
                `samples` name an unlisted column, or a sample column is PII.

        """
        if self.columns != "*":
            if not self.columns:
                msg = "columns must list at least one column or be '*'"
                raise ValueError(msg)
            if len(set(self.columns)) != len(self.columns):
                msg = "columns must not repeat"
                raise ValueError(msg)
            unlisted = sorted((set(self.pii) | set(self.samples)) - set(self.columns))
            if unlisted:
                names = ", ".join(unlisted)
                msg = f"pii and samples name columns not in 'columns': {names}"
                raise ValueError(msg)
        pii_samples = sorted(set(self.samples) & set(self.pii))
        if pii_samples:
            msg = f"PII columns cannot be samples: {', '.join(pii_samples)}"
            raise ValueError(msg)
        return self


class FunctionAccess(PolicyModel):
    """Functions a profile may call on top of the engine's built-in allowlist.

    Attributes:
        allow: tuple[str, ...] - Extra function names, matched case-insensitively.

    """

    allow: tuple[Identifier, ...] = ()


class Profile(PolicyModel):
    """What one kind of caller may see and how far its queries may go.

    Attributes:
        limits: Limits - Bounds on one request.
        explain: ExplainThresholds - Planner cost thresholds.
        allow_recursive_cte: bool - Whether `WITH RECURSIVE` is allowed.
        tables: dict[str, TableAccess] - Visible tables as `schema.table`.
        functions: FunctionAccess - Extra allowed functions.

    """

    limits: Limits = Field(default_factory=Limits)
    explain: ExplainThresholds = Field(default_factory=ExplainThresholds)
    allow_recursive_cte: bool = False
    tables: dict[TableName, TableAccess] = Field(min_length=1)
    functions: FunctionAccess = Field(default_factory=FunctionAccess)
