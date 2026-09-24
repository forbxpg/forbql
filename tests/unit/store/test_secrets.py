from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from forbql.cli import app
from forbql.store import SecretKey, StoreError

if TYPE_CHECKING:
    from pathlib import Path

DSN = "postgresql://reader:pa55@db.internal:5432/bank"
KEY = SecretKey(b"k" * 32)


def test_a_sealed_secret_opens_in_its_place():
    sealed = KEY.seal(DSN, context="default/bank/")

    assert DSN.encode() not in sealed.blob
    assert KEY.open(sealed, context="default/bank/") == DSN


def test_sealing_twice_gives_different_bytes():
    assert KEY.seal(DSN, context="c").blob != KEY.seal(DSN, context="c").blob


def test_a_secret_moved_to_another_place_does_not_open():
    sealed = KEY.seal(DSN, context="default/bank/")

    with pytest.raises(StoreError, match="changed or moved"):
        KEY.open(sealed, context="default/shop/")


def test_a_changed_secret_does_not_open():
    sealed = KEY.seal(DSN, context="c")
    flipped = sealed.blob[:-1] + bytes([sealed.blob[-1] ^ 1])

    with pytest.raises(StoreError, match="changed or moved"):
        KEY.open(replace(sealed, blob=flipped), context="c")


def test_another_key_names_both_keys():
    other = SecretKey(b"o" * 32)
    sealed = other.seal(DSN, context="c")

    with pytest.raises(StoreError) as caught:
        KEY.open(sealed, context="c")

    assert other.key_id in str(caught.value)
    assert KEY.key_id in str(caught.value)


def test_the_key_comes_from_the_variable_first(tmp_path: Path):
    file = tmp_path / "key"
    file.write_text(SecretKey.generate() + "\n", encoding="utf-8")
    value = SecretKey.generate()

    assert SecretKey.load(value, file).key_id == SecretKey.load(value, None).key_id
    assert SecretKey.load(None, file).key_id != SecretKey.load(value, None).key_id


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (None, "set FORBQL_SECRET_KEY"),
        ("c2hvcnQ", "must be 32 bytes"),
        ("not base64 at all!", "not base64url"),
    ],
)
def test_no_usable_key_no_start(value: str | None, message: str):
    with pytest.raises(StoreError, match=message):
        SecretKey.load(value, None)


def test_keygen_prints_a_key_that_loads():
    result = CliRunner().invoke(app, ["store", "keygen"])

    assert result.exit_code == 0
    assert SecretKey.load(result.stdout.strip(), None).key_id
