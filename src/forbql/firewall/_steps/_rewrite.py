"""Last step: the SQL handed to the database must pass the checks again, unchanged."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forbql.firewall._rule_id import RuleId
from forbql.firewall._verdict import Violation

if TYPE_CHECKING:
    from forbql.firewall._verdict import Verdict


def check_rewrite(first: Verdict, again: Verdict) -> list[Violation]:
    """Compare the verdict on a query with the verdict on the SQL it was rewritten to.

    The database runs the rewritten SQL. If checking it again refuses it, changes it or
    masks other columns, the parser read the two differently, and the firewall would
    have approved one query and handed over another.

    Args:
        first: Verdict - The verdict on what the caller sent; allowed.
        again: Verdict - The verdict on `first.sql`.

    Returns:
        list[Violation] - One violation when the two differ; none when they agree.

    """
    if again.allowed and again.sql == first.sql and again.masks == first.masks:
        return []
    return [
        Violation(
            rule=RuleId.UNSTABLE_REWRITE,
            message="the firewall cannot rewrite this query into SQL that reads alike",
            hint="write it more plainly: ordinary string literals, no charset prefixes",
        ),
    ]
