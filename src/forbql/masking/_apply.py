"""Masks applied to whole result rows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._strategies import mask_value

if TYPE_CHECKING:
    from collections.abc import Sequence

    from forbql.firewall import ColumnMask


type __Row = tuple[object, ...]


def apply_masks(
    rows: Sequence[__Row],
    masks: Sequence[ColumnMask],
    key: bytes | None,
) -> tuple[__Row, ...]:
    """Mask the planned output columns of every row.

    Args:
        rows: Sequence[Row] - Rows from the engine.
        masks: Sequence[ColumnMask] - Positions and strategies from the verdict.
        key: bytes | None - HMAC key for the `hash` strategy.

    Returns:
        tuple[Row, ...] - Rows with masked columns replaced.

    """
    if not masks:
        return tuple(rows)

    by_position = {mask.position: mask for mask in masks}
    return tuple(
        tuple(
            mask_value(
                value,
                by_position[position].strategy,
                keep_last=by_position[position].keep_last,
                key=key,
            )
            if position in by_position
            else value
            for position, value in enumerate(row)
        )
        for row in rows
    )
