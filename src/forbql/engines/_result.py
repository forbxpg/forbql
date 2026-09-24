"""Rows a query returned, and the caps that bound them while they stream in."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from forbql.policy import Limits


type Row = tuple[object, ...]


@dataclass(frozen=True, slots=True)
class ResultSet:
    """Rows of one query.

    Attributes:
        columns: tuple[str, ...] - Output column names.
        rows: tuple[Row, ...] - The rows, after caps.
        truncated: bool - Whether a cap cut rows or cells.
        size: int - Bytes of the rows, as the caps counted them.

    """

    size: int
    truncated: bool
    rows: tuple[Row, ...]
    columns: tuple[str, ...]


def _size(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, bytes):
        return len(value)
    return len(str(value).encode())


def _cut(value: object, limit: int) -> tuple[object, bool]:
    if isinstance(value, bytes) and len(value) > limit:
        return value[:limit], True
    if isinstance(value, str) and len(value.encode()) > limit:
        return value.encode()[:limit].decode(errors="ignore"), True
    return value, False


class Collector:
    """Takes rows as they stream in and stops at the profile's caps.

    Args:
        limits: Limits - Rows, result bytes and cell bytes allowed.

    """

    _limits: Limits
    _rows: list[Row]
    _size: int
    _truncated: bool

    def __init__(self, limits: Limits) -> None:
        self._limits = limits
        self._rows = []
        self._size = 0
        self._truncated = False

    def add(self, row: Sequence[object]) -> bool:
        """Keep a row if it fits.

        Args:
            row: Sequence[object] - The row from the driver.

        Returns:
            bool - False once a cap is reached: stop fetching.

        """
        if len(self._rows) >= self._limits.max_rows:
            self._truncated = True
            return False

        cells: list[object] = []
        for val in row:
            cell, cut = _cut(val, self._limits.max_cell_bytes)
            self._truncated = self._truncated or cut
            cells.append(cell)

        size = sum(_size(cell) for cell in cells)
        if self._size + size > self._limits.max_result_bytes:
            self._truncated = True
            return False

        self._rows.append(tuple(cells))
        self._size += size
        return True

    def result(self, columns: Sequence[str]) -> ResultSet:
        """Return what was collected.

        Args:
            columns: Sequence[str] - Output column names.

        Returns:
            ResultSet - The capped rows.

        """
        return ResultSet(
            columns=tuple(columns),
            rows=tuple(self._rows),
            truncated=self._truncated,
            size=self._size,
        )
