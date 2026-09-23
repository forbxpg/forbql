"""Hints that name only what the profile can see."""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


_SHOWN = 10


def nearest(word: str, candidates: Iterable[str], label: str) -> str | None:
    """Suggest visible names close to a wrong one, or list some of them.

    Args:
        word: str - The name the caller wrote.
        candidates: Iterable[str] - Visible names only.
        label: str - What the names are, such as "columns".

    Returns:
        str | None - The hint, or None when there is nothing visible to suggest.

    """
    names = sorted(set(candidates))
    if not names:
        return None

    close = difflib.get_close_matches(word, names, n=3, cutoff=0.6)
    if close:
        return f"nearest allowed {label}: {', '.join(close)}"

    more = f" (and {len(names) - _SHOWN} more)" if len(names) > _SHOWN else ""
    return f"allowed {label}: {', '.join(names[:_SHOWN])}{more}"
