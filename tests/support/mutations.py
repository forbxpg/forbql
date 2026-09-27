"""Queries from the corpora, spoiled the ways parsers and databases disagree about."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING

from hypothesis import strategies as st

from forbql import Engine
from support.corpus import (
    PROFILE,
    attack_runs,
    connection_name,
    demo_firewall,
    legitimate_runs,
)
from support.spider import PROFILE as ANYONE
from support.spider import connection, spider_firewall, spider_queries

if TYPE_CHECKING:
    from collections.abc import Callable

    from forbql import Firewall

_SPACES = (" ", "\t", "\n", "\r\n", "  ", "\u00a0", "\u2028", "\u200b", "\f", "\v")
_BODIES = ("x", "*", "/", "'", '"', ";", "--", "$$", "`", "*/ x /*", "\n")
_WORD = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
_LITERAL = re.compile(r"'([^'\\]*)'")
_NUMBER = re.compile(r"\b\d+\b")

_QUOTES = {Engine.POSTGRES: '"', Engine.MYSQL: "`", Engine.SQLITE: '"'}
_LITERALS: dict[Engine, tuple[str, ...]] = {
    Engine.POSTGRES: ("E'{}'", "U&'{}'", "$${}$$", "$q${}$q$", "'{}' ", "e'{}'"),
    Engine.MYSQL: ('"{}"', "N'{}'", "_utf8mb4'{}'", "'{}' ''", "x'{}'"),
    Engine.SQLITE: ('"{}"', "X'{}'", "'{}' || ''"),
}
_COMMENTS: dict[Engine, tuple[str, ...]] = {
    Engine.POSTGRES: ("/*{}*/", "/* /* {} */ */", "--{}\n"),
    Engine.MYSQL: ("/*{}*/", "/*!{}*/", "-- {}\n", "--{}\n", "#{}\n"),
    Engine.SQLITE: ("/*{}*/", "--{}\n", "/*{}"),
}
_NUMBERS: dict[Engine, tuple[str, ...]] = {
    Engine.POSTGRES: ("{}.0", "{}e0", "0{}", "{}::int"),
    Engine.MYSQL: ("{}.0", "{}e0", "0x{:x}", "0{}"),
    Engine.SQLITE: ("{}.0", "{}e0", "0x{:x}", "+{}"),
}


@dataclass(frozen=True, slots=True)
class Target:
    """A query and the firewall that judges it.

    Attributes:
        firewall: Firewall - The firewall.
        connection: str - Connection name in its policy.
        profile: str - Profile name.
        engine: Engine - The connection's engine.
        sql: str - The query before spoiling.

    """

    firewall: Firewall
    connection: str
    profile: str
    engine: Engine
    sql: str


@cache
def demo_targets() -> tuple[Target, ...]:
    demo = demo_firewall()
    runs = [(case.sql, engine) for case, engine in [*legitimate_runs(), *attack_runs()]]
    return tuple(
        Target(demo, connection_name(engine), PROFILE, engine, sql)
        for sql, engine in runs
    )


@cache
def targets() -> tuple[Target, ...]:
    found = list(demo_targets())
    found += [
        Target(
            spider_firewall(query.db),
            connection(query.db),
            ANYONE,
            Engine.SQLITE,
            query.sql,
        )
        for query in spider_queries()
    ]
    return tuple(found)


def _at(pattern: re.Pattern[str], sql: str, draw: st.DrawFn) -> re.Match[str] | None:
    found = list(pattern.finditer(sql))
    return draw(st.sampled_from(found)) if found else None


def _replace(sql: str, match: re.Match[str], text: str) -> str:
    return sql[: match.start()] + text + sql[match.end() :]


def _space(draw: st.DrawFn, sql: str, _engine: Engine) -> str | None:
    at = _at(re.compile(r" "), sql, draw)
    return None if at is None else _replace(sql, at, draw(st.sampled_from(_SPACES)))


def _comment(draw: st.DrawFn, sql: str, engine: Engine) -> str | None:
    at = _at(re.compile(r" "), sql, draw)
    if at is None:
        return None
    form = draw(st.sampled_from(_COMMENTS[engine]))
    return _replace(sql, at, f" {form.format(draw(st.sampled_from(_BODIES)))} ")


def _case(draw: st.DrawFn, sql: str, _engine: Engine) -> str | None:
    change: Callable[[str], str] = draw(
        st.sampled_from((str.upper, str.lower, str.swapcase, str.title)),
    )
    word = _at(_WORD, sql, draw)
    return change(sql) if word is None else _replace(sql, word, change(word[0]))


def _quote(draw: st.DrawFn, sql: str, engine: Engine) -> str | None:
    word = _at(_WORD, sql, draw)
    quote = _QUOTES[engine]
    return None if word is None else _replace(sql, word, f"{quote}{word[0]}{quote}")


def _literal(draw: st.DrawFn, sql: str, engine: Engine) -> str | None:
    literal = _at(_LITERAL, sql, draw)
    if literal is None:
        return None
    form = draw(st.sampled_from(_LITERALS[engine]))
    return _replace(sql, literal, form.format(literal[1]))


def _number(draw: st.DrawFn, sql: str, engine: Engine) -> str | None:
    number = _at(_NUMBER, sql, draw)
    if number is None:
        return None
    form = draw(st.sampled_from(_NUMBERS[engine]))
    return _replace(sql, number, form.format(int(number[0])))


_MUTATIONS = (_space, _comment, _case, _quote, _literal, _number)


@st.composite
def spoiled(
    draw: st.DrawFn,
    pool: tuple[Target, ...] | None = None,
) -> tuple[Target, str]:
    """Pick a query and spoil it up to three times.

    Args:
        pool: tuple[Target, ...] | None - Queries to pick from; every corpus by default.

    Returns:
        tuple[Target, str] - The target and the spoiled query.

    """
    target = draw(st.sampled_from(pool or targets()))
    sql = target.sql
    for _ in range(draw(st.integers(min_value=1, max_value=3))):
        mutate = draw(st.sampled_from(_MUTATIONS))
        sql = mutate(draw, sql, target.engine) or sql
    return target, sql
