"""What a model reads: forbql's own words, then the data in a block marked untrusted.

Rows, comments, glossary text and examples come from outside forbql; a model must
read them as data, never as instructions. They travel in one block whose delimiters
carry a random nonce, so no value can close it early.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from fastmcp.tools import ToolResult
from mcp.types import TextContent

if TYPE_CHECKING:
    from collections.abc import Sequence

ROWS = 200
"""Rows a model receives at most, whatever the profile allows."""

BYTES = 30_000
"""Bytes of rows a model receives at most, so a wide result fits its context."""

CELL = 500
"""Characters of one value a model receives at most."""

# C0 and C1 controls but tab and newline, bidirectional overrides, zero-width marks.
_HIDDEN = re.compile(
    r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]",
)
_ESCAPES = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


@dataclass(frozen=True, slots=True)
class Fitted:
    """Rows cut to the budget, and what cut them.

    Attributes:
        rows: list[list[str | None]] - The rows as text; NULL stays None.
        cut_by: str | None - `limit` (the profile's), `rows` or `bytes`; None
            when every row is here.
        cells_cut: bool - Whether a long value was shortened.

    """

    rows: list[list[str | None]]
    cut_by: str | None
    cells_cut: bool


def clean(text: str) -> str:
    """Remove what a person would not see but a model would read.

    Args:
        text: str - Text from outside forbql.

    Returns:
        str - The text without terminal escapes, control characters, bidirectional
            overrides and zero-width marks.

    """
    return _HIDDEN.sub("", _ESCAPES.sub("", text))


def fit(
    rows: Sequence[Sequence[object]],
    *,
    limited: bool,
    max_rows: int = ROWS,
) -> Fitted:
    """Cut rows to the budget: at most `max_rows`, `BYTES` and `CELL` per value.

    Args:
        rows: Sequence[Sequence[object]] - Masked rows from a run.
        limited: bool - Whether the profile's row limit already cut them.
        max_rows: int - Rows to keep at most.

    Returns:
        Fitted - The rows and what cut them.

    """
    kept: list[list[str | None]] = []
    size, cells_cut, cut_by = 0, False, "limit" if limited else None
    for row in rows:
        if len(kept) == max_rows:
            cut_by = "rows"
            break
        cells = [None if value is None else clean(str(value)) for value in row]
        if any(cell is not None and len(cell) > CELL for cell in cells):
            cells_cut = True
            cells = [
                cell[: CELL - 1] + "…"
                if cell is not None and len(cell) > CELL
                else cell
                for cell in cells
            ]
        size += len(json.dumps(cells, ensure_ascii=False).encode())
        if size > BYTES:
            cut_by = "bytes"
            break
        kept.append(cells)
    return Fitted(rows=kept, cut_by=cut_by, cells_cut=cells_cut)


def untrusted(payload: object) -> str:
    """Wrap data from outside forbql in a block no value inside can close.

    Args:
        payload: object - What to wrap, as JSON.

    Returns:
        str - The block.

    """
    nonce = secrets.token_hex(8)
    body = json.dumps(payload, ensure_ascii=False, indent=1, default=str)
    return (
        f'<untrusted-data nonce="{nonce}">\n{body}\n</untrusted-data nonce="{nonce}">'
    )


def reply(
    summary: str,
    payload: dict[str, object] | None = None,
    *,
    error: bool = False,
) -> ToolResult:
    """Answer a tool call: forbql's summary, then the data, marked untrusted.

    Args:
        summary: str - What forbql says about the result; its own words.
        payload: dict[str, object] | None - The data; None when there is none.
        error: bool - Whether the call could not be answered at all.

    Returns:
        ToolResult - Text for the model and the same data as structured content,
            its text cleaned of hidden characters.

    """
    data = None if payload is None else _cleaned(payload)
    text = summary if data is None else f"{summary}\n{untrusted(data)}"
    return ToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=data,
        is_error=error,
    )


def _cleaned[T](value: T) -> T:
    """Clean every string in a structure.

    Args:
        value: T - Strings, lists and dicts of them, or anything else.

    Returns:
        T - The same structure, its strings cleaned.

    """
    if isinstance(value, str):
        return cast("T", clean(value))
    if isinstance(value, dict):
        return cast(
            "T",
            {k: _cleaned(v) for k, v in cast("dict[str, object]", value).items()},
        )
    if isinstance(value, (list, tuple)):
        return cast("T", [_cleaned(v) for v in cast("list[object]", value)])
    return value
