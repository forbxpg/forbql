from __future__ import annotations

from forbql.firewall._hints import nearest


def test_close_names_are_suggested():
    assert (
        nearest("balanse", ["balance", "status"], "columns")
        == "nearest allowed columns: balance"
    )


def test_far_names_list_what_is_allowed():
    hint = nearest("zzz", [f"c{i:02}" for i in range(12)], "columns")

    assert (
        hint
        == "allowed columns: c00, c01, c02, c03, c04, c05, c06, c07, c08, c09 (and 2 more)"
    )


def test_nothing_visible_means_no_hint():
    assert nearest("anything", [], "tables") is None
