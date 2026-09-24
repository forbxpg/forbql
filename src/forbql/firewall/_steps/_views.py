"""Views run with their owner's rights, so their definitions pass the allowlist."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forbql.firewall._rule_id import RuleId
from forbql.firewall._verdict import Violation

from ._functions import check_functions
from ._parse import parse

if TYPE_CHECKING:
    from forbql.firewall._context import CheckContext


def check_view(definition: str | None, ctx: CheckContext) -> list[Violation]:
    """Check a view's definition against the profile's function allowlist.

    Args:
        definition: str | None - The view's query, or its `CREATE VIEW` statement,
            whose query the check walks into; None when the role may not read it.
        ctx: CheckContext - Inputs of the check.

    Returns:
        list[Violation] - Problems found; a definition nobody can read is one.

    """
    if definition is None:
        return [
            Violation(
                rule=RuleId.PARSE_ERROR,
                message="the view's definition cannot be read",
                hint="let the role read view definitions (SHOW VIEW on MySQL)",
            ),
        ]
    tree = parse(definition, ctx)
    if isinstance(tree, list):
        return tree
    return check_functions(tree, ctx)
