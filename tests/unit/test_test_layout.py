"""Two test modules with the same package and file name: pytest silently runs one."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

TESTS = Path(__file__).parents[1]


def test_no_two_test_modules_share_a_name():
    names = Counter(
        f"{path.parent.name}/{path.name}"
        for path in TESTS.rglob("test_*.py")
        if (path.parent / "__init__.py").exists()
    )

    assert [name for name, count in names.items() if count > 1] == []
