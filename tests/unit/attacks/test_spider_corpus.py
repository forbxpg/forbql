"""The adapted Spider set holds what the false-block report measures."""

from __future__ import annotations

from support.spider import (
    PROFILE,
    connection,
    spider_firewall,
    spider_queries,
    spider_schemas,
)


def test_every_query_has_its_database():
    assert {query.db for query in spider_queries()} == set(spider_schemas())


def test_each_distinct_query_counts_once():
    pairs = [(query.db, query.sql) for query in spider_queries()]

    assert len(pairs) == len(set(pairs)) == 564
    assert len(spider_schemas()) == 20


def test_the_profile_sees_every_table_and_column():
    for db, tables in spider_schemas().items():
        visible = spider_firewall(db).visible(connection(db), PROFILE)
        assert visible == {f"main.{name}": columns for name, columns in tables.items()}
