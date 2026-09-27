"""What the firewall lets through, it lets through again unchanged.

The database runs the SQL the firewall regenerated, not what the caller sent; if that
SQL read differently a second time, the firewall would have approved one query and
handed the database another.
"""

from __future__ import annotations

from hypothesis import given

from support.mutations import Target, spoiled


@given(spoiled())
def test_an_allowed_query_regenerates_to_itself(spoiled_query: tuple[Target, str]):
    target, sql = spoiled_query
    first = target.firewall.check(
        sql,
        connection=target.connection,
        profile=target.profile,
    )
    if not first.allowed:
        return
    assert first.sql is not None

    again = target.firewall.check(
        first.sql,
        connection=target.connection,
        profile=target.profile,
    )

    assert again.allowed, (sql, first.sql, again.violations)
    assert again.sql == first.sql, sql
    assert again.masks == first.masks, sql
