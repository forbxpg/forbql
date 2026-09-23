"""Everyday analytics on the demo bank: the firewall must let them through.

A block recorded in `known_block` is a published false positive; the test fails when it
disappears, so the record stays true.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from support.corpus import LegitimateCase, legitimate_runs, rules_of, run_id

if TYPE_CHECKING:
    from forbql import Engine


@pytest.mark.parametrize(
    ("case", "engine"),
    legitimate_runs(),
    ids=[run_id(run) for run in legitimate_runs()],
)
def test_legitimate_query_passes(case: LegitimateCase, engine: Engine):
    if engine in case.known_block:
        pytest.xfail(case.known_block[engine])

    assert rules_of(case.sql, engine) == set()
