"""The corpus itself: unique ids, every rule covered, honest pending notes."""

from __future__ import annotations

from collections import Counter

from forbql import RuleId
from support.corpus import attack_files, attack_runs, legitimate_files

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
