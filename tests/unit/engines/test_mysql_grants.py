from __future__ import annotations

import pytest

from forbql.engines.mysql._grants import read_grants

READER = (
    "GRANT USAGE ON *.* TO `forbql_reader`@`%`",
    "GRANT SELECT, SHOW VIEW ON `bank`.`account_totals` TO `forbql_reader`@`%`",
    "GRANT SELECT ON `bank`.`accounts` TO `forbql_reader`@`%`",
    "GRANT SELECT (`created_at`, `email`, `id`) ON `bank`.`clients` TO `forbql_reader`@`%`",
)


def test_reading_the_current_database_passes():
    found = read_grants(READER, "bank")

    assert found.refusals == ()
    assert found.warnings == ()


def test_reading_a_whole_database_passes():
    assert read_grants(["GRANT SELECT ON `bank`.* TO `r`@`%`"], "bank").ok


@pytest.mark.parametrize(
    ("line", "refusal"),
    [
        (
            "GRANT SELECT, INSERT ON `bank`.`accounts` TO `r`@`%`",
            "the account may INSERT on `bank`.`accounts`",
        ),
        (
            "GRANT SELECT (`id`), UPDATE (`email`) ON `bank`.`clients` TO `r`@`%`",
            "the account may UPDATE on `bank`.`clients`",
        ),
        (
            "GRANT FILE, PROCESS ON *.* TO `r`@`%`",
            "the account holds global privileges: FILE, PROCESS",
        ),
        (
            "GRANT SELECT ON *.* TO `r`@`%`",
            "the account holds global privileges: SELECT",
        ),
        (
            "GRANT BACKUP_ADMIN,SYSTEM_USER ON *.* TO `r`@`%`",
            "the account holds global privileges: BACKUP_ADMIN, SYSTEM_USER",
        ),
        (
            "GRANT SELECT ON `bank`.`accounts` TO `r`@`%` WITH GRANT OPTION",
            "the account may grant its privileges on `bank`.`accounts`",
        ),
        (
            "GRANT `analysts`@`%` TO `r`@`%`",
            "the account holds a role or a grant forbql cannot read",
        ),
        (
            "GRANT PROXY ON ``@`` TO `r`@`%`",
            "the account may PROXY on ``@``",
        ),
        (
            "GRANT EXECUTE ON PROCEDURE `bank`.`refresh` TO `r`@`%`",
            "the account may EXECUTE on PROCEDURE `bank`.`refresh`",
        ),
    ],
    ids=[
        "table",
        "column",
        "global",
        "select-everywhere",
        "dynamic",
        "grant-option",
        "role",
        "proxy",
        "routine",
    ],
)
def test_anything_beyond_reading_is_refused(line: str, refusal: str):
    found = read_grants([*READER, line], "bank")

    assert len(found.refusals) == 1
    assert found.refusals[0].startswith(refusal)


def test_reading_another_database_is_a_warning():
    found = read_grants([*READER, "GRANT SELECT ON `shop`.* TO `r`@`%`"], "bank")

    assert found.ok
    assert found.warnings == ("the account may read `shop`.* outside bank",)
