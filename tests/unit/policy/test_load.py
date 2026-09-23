from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from forbql.policy import (
    Engine,
    Limits,
    MaskStrategy,
    PiiClass,
    PolicyError,
    UnknownProfileError,
    load_policy,
    parse_policy,
    policy_hash,
)

if TYPE_CHECKING:
    from pathlib import Path

POLICY = """
version: 1
connections:
  bank:
    engine: postgres
    profiles:
      analyst:
        limits: { max_rows: 500 }
        tables:
          public.accounts: { columns: "*" }
          public.clients:
            columns: [id, region, email, phone, passport]
            pii:
              email: { class: mask, strategy: partial }
              phone: { class: aggregate_only }
              passport: { class: deny }
            samples: [region]
"""


def test_parses_a_full_policy():
    policy = parse_policy(POLICY)

    connection = policy.connection("bank")
    profile = policy.profile("bank", "analyst")
    clients = profile.tables["public.clients"]
    assert connection.engine is Engine.POSTGRES
    assert profile.limits.max_rows == 500
    assert profile.limits.max_joins == Limits().max_joins
    assert profile.tables["public.accounts"].columns == "*"
    assert clients.pii["email"].pii_class is PiiClass.MASK
    assert clients.pii["email"].strategy is MaskStrategy.PARTIAL
    assert clients.pii["passport"].pii_class is PiiClass.DENY
    assert clients.samples == ("region",)


def test_loads_from_a_file(tmp_path: Path):
    path = tmp_path / "forbql.yaml"
    path.write_text(POLICY, encoding="utf-8")

    assert load_policy(path) == parse_policy(POLICY)


def test_missing_file_is_a_policy_error(tmp_path: Path):
    with pytest.raises(PolicyError, match="cannot read"):
        load_policy(tmp_path / "absent.yaml")


def test_unknown_profile_is_reported_by_name():
    policy = parse_policy(POLICY)

    with pytest.raises(UnknownProfileError, match="profile 'admin'"):
        policy.profile("bank", "admin")
    with pytest.raises(UnknownProfileError, match="connection 'shop'"):
        policy.profile("shop", "analyst")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (("version: 1", "version: 2"), "version"),
        (("engine: postgres", "engine: oracle"), "engine"),
        (("limits: { max_rows: 500 }", "limits: { max_rows: 0 }"), "max_rows"),
        (("limits: { max_rows: 500 }", "limits: { max_rowz: 5 }"), "max_rowz"),
        (("public.accounts", "accounts"), "tables"),
        (("region, email", "region, region, email"), "must not repeat"),
        (("samples: [region]", "samples: [secret]"), "not in 'columns'"),
        (("samples: [region]", "samples: [email]"), "cannot be samples"),
        (
            ("{ class: mask, strategy: partial }", "{ class: mask }"),
            "requires a strategy",
        ),
        (
            ("{ class: aggregate_only }", "{ class: aggregate_only, strategy: hash }"),
            "no strategy",
        ),
        (("strategy: partial }", "strategy: hash, keep_last: 2 }"), "keep_last"),
        (('{ columns: "*" }', "{ columns: [] }"), "at least one column"),
    ],
)
def test_invalid_policy_fails_at_load_time(change: tuple[str, str], message: str):
    old, new = change
    assert old in POLICY

    with pytest.raises(PolicyError, match=message):
        parse_policy(POLICY.replace(old, new, 1))


def test_explain_thresholds_must_be_ordered():
    text = POLICY.replace(
        "limits:",
        "explain: { confirm_cost: 10, block_cost: 5 }\n        limits:",
    )

    with pytest.raises(PolicyError, match="confirm_cost must be below block_cost"):
        parse_policy(text)


def test_duplicate_key_is_rejected():
    text = POLICY.replace(
        'public.accounts: { columns: "*" }',
        'public.accounts: { columns: "*" }\n          public.accounts: { columns: [id] }',
    )

    with pytest.raises(PolicyError, match=r"duplicate key 'public\.accounts'"):
        parse_policy(text)


def test_non_yaml_is_rejected():
    with pytest.raises(PolicyError, match="invalid YAML"):
        parse_policy("version: [1")


def test_hash_ignores_formatting_but_not_meaning():
    policy = parse_policy(POLICY)
    reformatted = parse_policy(
        "# reviewed\n"
        + POLICY.replace("{ max_rows: 500 }", "\n          max_rows: 500"),
    )
    changed = parse_policy(POLICY.replace("max_rows: 500", "max_rows: 501"))

    assert policy_hash(reformatted) == policy_hash(policy)
    assert policy_hash(changed) != policy_hash(policy)
    assert policy_hash(policy).startswith("sha256:")


def test_json_schema_uses_yaml_names():
    schema = json.dumps(parse_policy(POLICY).model_json_schema(by_alias=True))

    assert '"class"' in schema
    assert '"pii_class"' not in schema
