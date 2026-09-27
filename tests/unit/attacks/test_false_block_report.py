"""The published false-block rate is the one the firewall has now."""

from __future__ import annotations

from support.false_blocks import REPORT, render


def test_the_report_matches_the_firewall():
    assert REPORT.read_text(encoding="utf-8") == render(), (
        "regenerate it: uv run python tests/support/false_blocks.py"
    )
