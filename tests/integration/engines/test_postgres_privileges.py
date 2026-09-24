"""The startup privilege check on the local stand, one right at a time.

Runs against: docker compose -f deploy/compose.yaml up -d --wait
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from forbql import Engine
from forbql.engines.postgres import PostgresEngine
from support.stand import ADMIN, READER, probe_account

if TYPE_CHECKING:
    from forbql.engines import PrivilegeReport

pytestmark = pytest.mark.integration


def report(dsn: str) -> PrivilegeReport:
    async def go() -> PrivilegeReport:
        engine = await PostgresEngine.connect(dsn)
        try:
            return await engine.check_privileges()
        finally:
            await engine.close()

    return asyncio.run(go())


def probe(grants: list[str], cleanup: tuple[str, ...] = ()) -> PrivilegeReport:
    with probe_account(Engine.POSTGRES, grants, cleanup) as dsn:
        return report(dsn)


def test_the_demo_reader_holds_nothing_to_refuse_or_warn_about():
    found = report(READER[Engine.POSTGRES])

    assert found.refusals == ()
    assert found.warnings == ()


def test_a_superuser_is_refused_without_further_questions():
    assert report(ADMIN[Engine.POSTGRES]).refusals == ("the role has SUPERUSER",)


def test_reading_everything_is_allowed():
    assert probe(["GRANT pg_read_all_data TO forbql_probe"]).ok


@pytest.mark.parametrize(
    ("grants", "cleanup", "refusal"),
    [
        (
            ["ALTER ROLE forbql_probe CREATEDB"],
            (),
            "the role has CREATEDB",
        ),
        (
            ["GRANT pg_monitor TO forbql_probe"],
            (),
            "the role is a member of pg_monitor",
        ),
        (
            ["GRANT INSERT ON accounts TO forbql_probe"],
            (),
            "the role may INSERT on public.accounts",
        ),
        (
            ["GRANT UPDATE (region) ON clients TO forbql_probe"],
            (),
            "the role may UPDATE on public.clients (region)",
        ),
        (
            [
                "CREATE TABLE probe_owned (id integer)",
                "ALTER TABLE probe_owned OWNER TO forbql_probe",
            ],
            ("DROP TABLE IF EXISTS probe_owned",),
            "the role owns public.probe_owned",
        ),
        (
            ["GRANT CREATE ON SCHEMA public TO forbql_probe"],
            (),
            "the role may CREATE in schema public",
        ),
        (
            ["GRANT CREATE ON DATABASE bank TO forbql_probe"],
            (),
            "the role may CREATE schemas in database bank",
        ),
        (
            [
                "CREATE SEQUENCE probe_sequence",
                "GRANT USAGE ON SEQUENCE probe_sequence TO forbql_probe",
            ],
            ("DROP SEQUENCE IF EXISTS probe_sequence",),
            "the role may use sequence public.probe_sequence",
        ),
        (
            [
                "CREATE EXTENSION postgres_fdw",
                "CREATE SERVER probe_server FOREIGN DATA WRAPPER postgres_fdw",
                "CREATE USER MAPPING FOR forbql_probe SERVER probe_server",
            ],
            (
                "DROP SERVER IF EXISTS probe_server CASCADE",
                "DROP EXTENSION IF EXISTS postgres_fdw",
            ),
            "the role may reach foreign server probe_server through a user mapping",
        ),
        (
            ["ALTER ROLE forbql_probe SET standard_conforming_strings = off"],
            (),
            "standard_conforming_strings is off",
        ),
    ],
    ids=[
        "attribute",
        "membership",
        "table",
        "column",
        "owner",
        "schema",
        "database",
        "sequence",
        "user-mapping",
        "string-literals",
    ],
)
def test_each_right_beyond_reading_is_refused(
    grants: list[str],
    cleanup: tuple[str, ...],
    refusal: str,
):
    found = probe(grants, cleanup)

    assert any(line.startswith(refusal) for line in found.refusals), found.refusals


def test_a_role_cannot_hide_its_rights_behind_its_search_path():
    # A schema of its own, searched before pg_catalog, with a pg_roles that lies.
    found = probe(
        [
            "ALTER ROLE forbql_probe CREATEDB",
            "CREATE SCHEMA probe_shadow",
            (
                "CREATE VIEW probe_shadow.pg_roles AS "
                "SELECT * FROM pg_catalog.pg_roles WHERE false"
            ),
            "GRANT USAGE ON SCHEMA probe_shadow TO forbql_probe",
            "GRANT SELECT ON probe_shadow.pg_roles TO forbql_probe",
            "ALTER ROLE forbql_probe SET search_path = probe_shadow, pg_catalog",
        ],
        ("DROP SCHEMA IF EXISTS probe_shadow CASCADE",),
    )

    assert "the role has CREATEDB" in found.refusals


def test_temporary_tables_are_a_warning_with_the_fix():
    found = probe(["GRANT TEMPORARY ON DATABASE bank TO forbql_probe"])

    assert found.ok
    assert found.warnings == (
        (
            "the role may create temporary tables: "
            "REVOKE TEMPORARY ON DATABASE bank FROM PUBLIC, forbql_probe;"
        ),
    )


def test_security_definer_functions_are_a_warning_with_the_fix():
    found = probe(
        [
            (
                "CREATE FUNCTION probe_definer() RETURNS integer "
                "LANGUAGE sql SECURITY DEFINER AS 'SELECT 1'"
            ),
        ],
        ("DROP FUNCTION IF EXISTS probe_definer()",),
    )

    assert found.ok
    assert found.warnings == (
        (
            "the role may execute SECURITY DEFINER function public.probe_definer(): "
            "REVOKE EXECUTE ON FUNCTION public.probe_definer() FROM PUBLIC;"
        ),
    )
