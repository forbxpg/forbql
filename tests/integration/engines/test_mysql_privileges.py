"""The startup privilege check on the local stand, from what SHOW GRANTS prints.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from forbql import Engine
from forbql.engines.mysql import MySQLEngine
from support.stand import ADMIN, READER, probe_account

if TYPE_CHECKING:
    from forbql.engines import PrivilegeReport

pytestmark = pytest.mark.integration


def report(dsn: str) -> PrivilegeReport:
    async def go() -> PrivilegeReport:
        engine = await MySQLEngine.connect(dsn)
        try:
            return await engine.check_privileges()
        finally:
            await engine.close()

    return asyncio.run(go())


def test_the_demo_reader_holds_nothing_to_refuse_or_warn_about():
    found = report(READER[Engine.MYSQL])

    assert found.refusals == ()
    assert found.warnings == ()


def test_the_owner_is_refused():
    refusals = report(ADMIN[Engine.MYSQL]).refusals

    assert any("global privileges" in line for line in refusals), refusals


def test_a_write_grant_is_refused():
    with probe_account(
        Engine.MYSQL,
        ["GRANT SELECT, INSERT ON bank.accounts TO 'forbql_probe'@'%'"],
    ) as dsn:
        found = report(dsn)

    assert found.refusals == ("the account may INSERT on `bank`.`accounts`",)


def test_reading_another_database_is_a_warning():
    with probe_account(
        Engine.MYSQL,
        [
            "GRANT SELECT ON bank.accounts TO 'forbql_probe'@'%'",
            "GRANT SELECT ON sys.* TO 'forbql_probe'@'%'",
        ],
    ) as dsn:
        found = report(dsn)

    assert found.ok
    assert found.warnings == ("the account may read `sys`.* outside bank",)
