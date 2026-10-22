from __future__ import annotations

from ssl import CERT_NONE, CERT_REQUIRED
from urllib.parse import urlsplit

import pytest

from forbql import Engine
from forbql.engines.mysql import MySQLEngine
from support.stand import ADMIN, PROBE, READER


def test_missing_ssl_mode_names_the_parameter():
    with pytest.raises(ValueError, match="ssl-mode"):
        MySQLEngine._tls("")


@pytest.mark.parametrize("mode", ["PREFERRED", "preferred", "Preferred"])
def test_preferred_is_refused(mode: str):
    with pytest.raises(ValueError, match="PREFERRED"):
        MySQLEngine._tls(f"ssl-mode={mode}")


def test_preferred_stays_refused_with_the_opt_in():
    with pytest.raises(ValueError, match="PREFERRED"):
        MySQLEngine._tls("ssl-mode=PREFERRED&forbql-insecure=1")


def test_disabled_without_the_opt_in_is_refused():
    with pytest.raises(ValueError, match="forbql-insecure=1"):
        MySQLEngine._tls("ssl-mode=disabled")


def test_a_value_other_than_1_is_not_the_opt_in():
    with pytest.raises(ValueError, match="forbql-insecure=1"):
        MySQLEngine._tls("ssl-mode=DISABLED&forbql-insecure=true")


@pytest.mark.parametrize(
    "query",
    [
        "ssl-mode=DISABLED&forbql-insecure=1",
        "forbql-insecure=1&ssl-mode=disabled",
    ],
)
def test_disabled_with_forbql_insecure_is_plaintext(query: str):
    try:
        outcome = MySQLEngine._tls(query)
    except ValueError as error:
        pytest.fail(str(error))

    assert outcome == (None, True)


def test_disabled_plaintext_still_rejects_certificate_files():
    with pytest.raises(ValueError, match="ssl-ca"):
        MySQLEngine._tls("ssl-mode=DISABLED&forbql-insecure=1&ssl-ca=/ca.pem")


def test_required_encrypts_without_checking_the_certificate():
    context, disabled = MySQLEngine._tls("ssl-mode=REQUIRED")

    assert context is not None
    assert context.verify_mode == CERT_NONE
    assert not context.check_hostname
    assert not disabled


def test_the_opt_in_does_not_change_required():
    try:
        context, disabled = MySQLEngine._tls("ssl-mode=REQUIRED&forbql-insecure=1")
    except ValueError as error:
        pytest.fail(str(error))

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


@pytest.mark.parametrize("role", [READER, ADMIN, PROBE])
def test_local_mysql_roles_opt_into_plaintext(role: dict[Engine, str]):
    context, disabled = MySQLEngine._tls(urlsplit(role[Engine.MYSQL]).query)

    assert context is None
    assert disabled is True
