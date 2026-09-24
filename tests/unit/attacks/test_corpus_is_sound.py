"""The corpus itself: unique ids, every rule covered, honest pending notes."""

from __future__ import annotations

from collections import Counter

import pytest
import yaml
from pydantic import ValidationError

from forbql import RuleId
from support.corpus import (
    AttackCase,
    attack_files,
    attack_runs,
    legitimate_files,
    load_yaml,
)

# Rules no query should reach: a crash inside the analysis, and a usability rule the
# database would enforce anyway.
NOT_ATTACKED = {RuleId.INTERNAL_ERROR, RuleId.AMBIGUOUS_COLUMN}


def test_ids_are_unique_across_both_corpora():
    ids = [case.id for file in attack_files() for case in file.cases]
    ids += [case.id for file in legitimate_files() for case in file.cases]

    assert [case_id for case_id, count in Counter(ids).items() if count > 1] == []


def test_every_rule_has_an_attack():
    attacked = {case.rule for case, _ in attack_runs()}

    assert set(RuleId) - NOT_ATTACKED - attacked == set()


def test_pending_names_only_dialects_the_case_runs_on():
    for case, _ in attack_runs():
        assert set(case.pending) <= set(case.dialects), case.id
        assert not case.pending or case.effects, case.id


def test_each_class_lives_in_its_own_file():
    classes = [file.attack_class for file in attack_files()]

    assert len(classes) == len(set(classes))


def test_a_repeated_key_is_refused():
    with pytest.raises(yaml.constructor.ConstructorError, match="duplicate key 'rule'"):
        load_yaml("id: x\nrule: unknown_column\nrule: table_not_allowed\n")


def test_a_case_needs_a_dialect():
    case: dict[str, object] = {
        "id": "x",
        "why": "y",
        "sql": "SELECT 1",
        "rule": "parse_error",
        "dialects": [],
    }

    with pytest.raises(ValidationError, match="at least 1"):
        AttackCase.model_validate(case)
