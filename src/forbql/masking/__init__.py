"""Masking of PII columns in result rows, by the positions the firewall planned."""

from __future__ import annotations

from ._apply import apply_masks
from ._strategies import mask_value

__all__ = ("apply_masks", "mask_value")
