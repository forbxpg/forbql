"""Reading `SHOW GRANTS`: an account may hold SELECT and SHOW VIEW, nothing more."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from forbql.engines._privileges import PrivilegeReport

if TYPE_CHECKING:
    from collections.abc import Iterable

_GRANT = re.compile(
    r"""
    ^GRANT\ (?P<privileges>.+?)
    \ ON\ (?P<target>.+?)
    \ TO\ \S+?
    (?P<option>\ WITH\ GRANT\ OPTION)?$
    """,
    re.VERBOSE,
)
_COLUMNS = re.compile(r"\s*\(.*?\)")
_READS = frozenset({"SELECT", "SHOW VIEW"})


def read_grants(lines: Iterable[str], database: str) -> PrivilegeReport:
    """Judge an account by the lines `SHOW GRANTS` prints for it.

    Args:
        lines: Iterable[str] - The lines, one `GRANT` statement each.
        database: str - The database the connection uses.

    Returns:
        PrivilegeReport - Anything beyond reading is refused; reading another
            database is a warning.

    """
    refusals: list[str] = []
    warnings: list[str] = []
    for line in lines:
        grant = _GRANT.match(line)
        if grant is None:
            refusals.append(
                f"the account holds a role or a grant forbql cannot read: {line}",
            )
            continue
        privileges = _privileges(grant["privileges"])
        target = grant["target"]
        if grant["option"]:
            refusals.append(f"the account may grant its privileges on {target}")
        if target == "*.*":
            if privileges != {"USAGE"}:
                names = ", ".join(sorted(privileges - {"USAGE"}))
                refusals.append(f"the account holds global privileges: {names}")
        elif extra := sorted(privileges - _READS):
            refusals.append(f"the account may {', '.join(extra)} on {target}")
        elif _database(target) != database:
            warnings.append(f"the account may read {target} outside {database}")
    return PrivilegeReport(refusals=tuple(refusals), warnings=tuple(warnings))


def _privileges(text: str) -> set[str]:
    """Split a privilege list, dropping column lists: `SELECT (a, b), INSERT`.

    Args:
        text: str - The privileges as `SHOW GRANTS` prints them.

    Returns:
        set[str] - Privilege names, upper case.

    """
    return {name.strip().upper() for name in _COLUMNS.sub("", text).split(",")}


def _database(target: str) -> str | None:
    """Return the database a grant's target names, or None for routines and proxies.

    Args:
        target: str - `` `db`.* `` or `` `db`.`table` ``.

    Returns:
        str | None - The database name.

    """
    match = re.match(r"^`((?:[^`]|``)+)`\.", target)
    return match[1].replace("``", "`") if match else None
