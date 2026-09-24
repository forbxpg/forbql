from __future__ import annotations

from forbql.engines import Collector
from forbql.policy import Limits


def test_rows_stop_at_max_rows():
    collector = Collector(Limits(max_rows=2))

    kept = [collector.add((n,)) for n in range(3)]
    result = collector.result(["n"])

    assert kept == [True, True, False]
    assert result.rows == ((0,), (1,))
    assert result.truncated is True


def test_long_cells_are_cut_to_max_cell_bytes():
    collector = Collector(Limits(max_cell_bytes=4))

    assert collector.add(("abcdefgh", b"12345678", 123456789))
    result = collector.result(["s", "b", "n"])

    assert result.rows == (("abcd", b"1234", 123456789),)
    assert result.truncated is True


def test_cut_never_splits_a_multibyte_character():
    collector = Collector(Limits(max_cell_bytes=5))

    assert collector.add(("日本語",))  # three bytes per character

    assert collector.result(["name"]).rows == (("日",),)


def test_result_stops_before_max_result_bytes():
    collector = Collector(Limits(max_result_bytes=10))

    assert collector.add(("12345",))
    assert collector.add(("12345",))
    assert not collector.add(("1",))

    result = collector.result(["v"])
    assert result.size == 10
    assert result.truncated is True


def test_small_results_are_not_truncated():
    collector = Collector(Limits())

    assert collector.add((1, None, "x"))

    assert collector.result(["a", "b", "c"]).truncated is False
