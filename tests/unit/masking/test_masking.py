from __future__ import annotations

import pytest

from forbql.firewall import ColumnMask
from forbql.masking import apply_masks, mask_value
from forbql.policy import MaskStrategy

KEY = b"k" * 32


def test_redact_hides_everything():
    assert (
        mask_value("client1@example.com", MaskStrategy.REDACT, keep_last=4, key=None)
        == "*****"
    )


def test_partial_keeps_the_last_characters():
    assert (
        mask_value("client1@example.com", MaskStrategy.PARTIAL, keep_last=4, key=None)
        == "*****.com"
    )


def test_partial_hides_short_values_entirely():
    assert mask_value("abc", MaskStrategy.PARTIAL, keep_last=4, key=None) == "*****"


def test_hash_is_stable_keyed_and_short():
    first = mask_value("a@b.c", MaskStrategy.HASH, keep_last=4, key=KEY)
    again = mask_value("a@b.c", MaskStrategy.HASH, keep_last=4, key=KEY)
    other_key = mask_value("a@b.c", MaskStrategy.HASH, keep_last=4, key=b"x" * 32)

    assert first == again
    assert first != other_key
    assert isinstance(first, str)
    assert len(first) == 16
    assert "a@b.c" not in first


def test_hash_without_a_key_refuses():
    with pytest.raises(ValueError, match="needs a key"):
        mask_value("a@b.c", MaskStrategy.HASH, keep_last=4, key=None)


@pytest.mark.parametrize("strategy", list(MaskStrategy))
def test_null_stays_null(strategy: MaskStrategy):
    assert mask_value(None, strategy, keep_last=4, key=KEY) is None


def test_only_planned_positions_are_masked():
    masks = [
        ColumnMask(
            position=1,
            column="main.clients.email",
            strategy=MaskStrategy.REDACT,
            keep_last=4,
        ),
    ]

    rows = apply_masks([(1, "a@b.c", "London"), (2, None, "Kazan")], masks, None)

    assert rows == ((1, "*****", "London"), (2, None, "Kazan"))


def test_no_masks_leaves_rows_alone():
    rows = [(1, "a@b.c")]

    assert apply_masks(rows, [], None) == ((1, "a@b.c"),)


def test_bytes_that_are_not_utf8_are_masked_not_refused():
    masked = mask_value(b"\xff\xfeab", MaskStrategy.PARTIAL, keep_last=2, key=None)

    assert masked == "*****ab"
