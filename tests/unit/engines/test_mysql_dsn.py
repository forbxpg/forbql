from __future__ import annotations

from ssl import CERT_NONE, CERT_REQUIRED

import pytest

from forbql.engines.mysql import MySQLEngine


def test_no_parameters_prefer_tls_like_the_mysql_client():
    assert MySQLEngine._tls("") == (None, False)


def test_disabled_turns_tls_off():
    assert MySQLEngine._tls("ssl-mode=disabled") == (None, True)


def test_required_encrypts_without_checking_the_certificate():
    context, disabled = MySQLEngine._tls("ssl-mode=REQUIRED")

    assert context is not None
    assert context.verify_mode == CERT_NONE
    assert not context.check_hostname
    assert not disabled


@pytest.mark.parametrize("mode", ["VERIFY_CA", "VERIFY_IDENTITY"])
def test_verify_modes_check_the_certificate(mode: str):
    context, _ = MySQLEngine._tls(f"ssl-mode={mode}")

    assert context is not None
    assert context.verify_mode == CERT_REQUIRED
    assert context.check_hostname is (mode == "VERIFY_IDENTITY")


@pytest.mark.parametrize(
    "query",
    [
        "sslmode=require",
        "ssl-mode=REQUIRED&charset=latin1",
        "ssl-mode=SOMETIMES",
        "ssl-ca=/ca.pem",
        "ssl-mode=PREFERRED&ssl-ca=/ca.pem",
    ],
)
def test_parameters_that_would_be_ignored_are_refused(query: str):
    with pytest.raises(ValueError, match=r"ssl|parameters"):
        MySQLEngine._tls(query)
