from __future__ import annotations

import pytest

from forbql.access import Capability, Grant, Principal, TokenParts

ANALYST = Grant(
    connection="bank",
    profile="analyst",
    capabilities=frozenset({Capability.SQL_CHECK, Capability.SQL_RUN}),
)


def test_a_grant_reads_from_its_short_form():
    assert Grant.parse("bank:analyst:sql.check, sql.run") == ANALYST


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("bank:analyst", "a grant is connection:profile"),
        ("bank::sql.run", "a grant is connection:profile"),
        ("bank:analyst:sql.run:extra", "a grant is connection:profile"),
        ("bank:analyst:sql.drop", "unknown capability sql.drop"),
    ],
)
def test_a_malformed_grant_is_refused(text: str, message: str):
    with pytest.raises(ValueError, match=message):
        Grant.parse(text)


def test_a_principal_may_only_what_a_grant_names():
    principal = Principal("token:1a2b3c4d5e6f", (ANALYST,))

    assert principal.may(Capability.SQL_RUN, connection="bank", profile="analyst")
    assert not principal.may(
        Capability.SCHEMA_READ,
        connection="bank",
        profile="analyst",
    )
    assert not principal.may(Capability.SQL_RUN, connection="bank", profile="auditor")
    assert not principal.may(Capability.SQL_RUN, connection="shop", profile="analyst")


def test_a_principal_without_grants_may_nothing():
    principal = Principal("token:1a2b3c4d5e6f")

    assert not any(
        principal.may(capability, connection="bank", profile="analyst")
        for capability in Capability
    )


def test_a_new_token_parses_back_and_matches_only_its_own_hash():
    token = TokenParts.new()

    parsed = TokenParts.parse(token.value)

    assert parsed == token
    assert token.value.startswith(f"fql_{token.token_id}_")
    assert token.matches(token.secret_hash())
    assert not token.matches(TokenParts.new().secret_hash())
    assert token.secret not in token.secret_hash()


def test_two_tokens_share_nothing():
    first, second = TokenParts.new(), TokenParts.new()

    assert first.token_id != second.token_id
    assert first.secret != second.secret


@pytest.mark.parametrize(
    "text",
    [
        "",
        "fql_",
        "Bearer fql_1a2b3c4d5e6f_" + "a" * 43,
        "fql_1A2B3C4D5E6F_" + "a" * 43,
        "fql_1a2b3c4d5e6f_" + "a" * 42,
        "fql_1a2b3c4d5e6f_" + "a" * 43 + "\n",
        "ghp_" + "a" * 36,
    ],
)
def test_anything_else_is_not_a_token(text: str):
    assert TokenParts.parse(text) is None
