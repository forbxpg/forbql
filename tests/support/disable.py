"""Switching one firewall rule off, for the test that every rule carries weight."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from forbql import RuleId, Violation
from forbql.firewall import _firewall
from forbql.firewall._steps import _parse

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

# Steps that return a tree when they pass: dropping all their violations must hand the
# tree on, as the step would have.
_GATES = ("check_statement",)
_STEPS = (
    (_firewall, "check_statement"),
    (_firewall, "check_objects"),
    (_firewall, "check_columns"),
    (_firewall, "check_functions"),
    (_firewall, "check_pii"),
    (_firewall, "check_complexity"),
    (_firewall, "enforce_limit"),
    (_parse, "_check_text"),
    (_parse, "_check_tokens"),
)


def _without(
    rule: RuleId,
    name: str,
    step: Callable[..., object],
) -> Callable[..., object]:
    def wrapped(*args: object) -> object:
        result = step(*args)
        if isinstance(result, tuple):
            parts = cast("tuple[object, ...]", result)
            violations = cast("list[Violation]", parts[-1])
            return (*parts[:-1], [v for v in violations if v.rule is not rule])
        if isinstance(result, list):
            found = cast("list[object]", result)
            kept = [v for v in found if isinstance(v, Violation) and v.rule is not rule]
            if name in _GATES and found and not kept:
                return args[0]
            return kept
        return result

    return wrapped


def disable_rule(monkeypatch: pytest.MonkeyPatch, rule: RuleId) -> None:
    for module, name in _STEPS:
        monkeypatch.setattr(module, name, _without(rule, name, getattr(module, name)))
