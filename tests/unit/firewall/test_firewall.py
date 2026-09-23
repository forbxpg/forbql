from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from forbql import Engine, Firewall, RuleId, SchemaSnapshot, check_structure
from forbql.firewall import _firewall
from forbql.policy import UnknownProfileError, parse_policy, policy_hash
from support.firewall import (
    HIDDEN,
    POLICY,
    SCHEMA,
    check,
    make_firewall,
    rules,
    snapshot,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_regenerated_sql_is_qualified(engine: Engine, firewall: Firewall):
    verdict = check(firewall, "SELECT id FROM accounts")

    assert verdict.sql is not None
    assert SCHEMA[engine] in verdict.sql
    assert verdict.structural_only is False


def test_verdict_carries_the_policy_hash(engine: Engine, firewall: Firewall):
    policy = parse_policy(POLICY.format(engine=engine.value, schema=SCHEMA[engine]))

    assert check(firewall, "SELECT id FROM accounts").policy_hash == policy_hash(policy)
    assert check(firewall, "DELETE FROM accounts").policy_hash == policy_hash(policy)


def test_without_a_snapshot_only_structure_is_checked(engine: Engine):
    firewall = make_firewall(engine, with_schema=False)

    unchecked = check(firewall, "SELECT api_key FROM secrets")
    rejected = check(firewall, "DELETE FROM accounts")

    assert unchecked.allowed
    assert unchecked.structural_only is True
    assert rules(rejected) == {RuleId.NOT_A_QUERY}


def test_check_structure_needs_no_policy(engine: Engine):
    verdict = check_structure("SELECT anything FROM anywhere", engine)

    assert verdict.allowed
    assert verdict.structural_only is True
    assert verdict.policy_hash is None
    assert verdict.sql is not None
    assert verdict.sql.endswith("LIMIT 1000")


def test_unknown_profile_raises(firewall: Firewall):
    with pytest.raises(UnknownProfileError):
        firewall.check("SELECT 1", connection="bank", profile="admin")


def test_snapshot_for_an_unknown_connection_raises():
    policy = parse_policy(POLICY.format(engine="postgres", schema="public"))

    with pytest.raises(UnknownProfileError, match="shop"):
        Firewall(policy, {"shop": snapshot(Engine.POSTGRES)})


def test_from_policy_reads_a_file(tmp_path: Path):
    path = tmp_path / "forbql.yaml"
    path.write_text(POLICY.format(engine="sqlite", schema="main"), encoding="utf-8")

    firewall = Firewall.from_policy(path, {"bank": snapshot(Engine.SQLITE)})

    assert check(firewall, "SELECT id FROM accounts").allowed


def test_failure_inside_a_step_is_a_rejection(
    firewall: Firewall,
    monkeypatch: pytest.MonkeyPatch,
):
    def explode(*_args: object) -> None:
        msg = "boom"
        raise KeyError(msg)

    monkeypatch.setattr(_firewall, "check_functions", explode)

    verdict = check(firewall, "SELECT id FROM accounts")

    assert rules(verdict) == {RuleId.INTERNAL_ERROR}


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM secret",
        "SELECT id FROM secrets",
        "SELECT internal_scor FROM clients",
        "SELECT pasport FROM clients",
        "SELECT curency FROM accounts",
        "SELECT descriptio FROM transactions",
        "SELECT c.api_ke FROM clients c",
    ],
)
def test_hints_never_name_hidden_objects(firewall: Firewall, sql: str):
    verdict = check(firewall, sql)

    assert not verdict.allowed
    for violation in verdict.violations:
        assert all(name not in (violation.hint or "") for name in HIDDEN)


def test_firewall_exposes_the_policy_hash(engine: Engine, firewall: Firewall):
    policy = parse_policy(POLICY.format(engine=engine.value, schema=SCHEMA[engine]))

    assert firewall.policy_hash == policy_hash(policy)


def test_table_missing_from_the_snapshot_is_not_visible(engine: Engine):
    policy = parse_policy(POLICY.format(engine=engine.value, schema=SCHEMA[engine]))
    schema = SCHEMA[engine]
    tables = {
        name: columns
        for name, columns in snapshot(engine).tables.items()
        if name != f"{schema}.transactions"
    }
    firewall = Firewall(
        policy,
        {"bank": SchemaSnapshot(default_schema=schema, tables=tables)},
    )

    assert rules(check(firewall, "SELECT id FROM transactions")) == {
        RuleId.TABLE_NOT_ALLOWED,
    }


def test_snapshot_tables_must_be_schema_qualified():
    with pytest.raises(ValidationError, match=r"schema\.table"):
        SchemaSnapshot(default_schema="public", tables={"accounts": ("id",)})
