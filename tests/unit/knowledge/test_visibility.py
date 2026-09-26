from __future__ import annotations

import pytest

from forbql.firewall import Firewall
from forbql.knowledge import (
    Example,
    GlossaryTerm,
    KnowledgeError,
    glossary_query,
    hidden_names,
    mentions,
    why_hidden,
)
from forbql.policy import Engine
from support.knowledge import CATALOG, CONNECTION, FIREWALL, POLICY


def term(sql: str = "status = 'open'", table: str = "public.accounts") -> GlossaryTerm:
    return GlossaryTerm(term="open", definition="Still open.", table=table, sql=sql)


def hidden(profile: str) -> frozenset[str]:
    return hidden_names(CATALOG, FIREWALL.visible(CONNECTION, profile))


def seen(entry: GlossaryTerm | Example, profile: str) -> bool:
    query = (
        entry.sql
        if isinstance(entry, Example)
        else glossary_query(entry, CATALOG, Engine.POSTGRES)
        if entry.sql
        else None
    )
    return (
        why_hidden(
            entry,
            query,
            firewall=FIREWALL,
            connection=CONNECTION,
            profile=profile,
            hidden=hidden(profile),
        )
        is None
    )


def test_the_expression_is_checked_as_a_query_over_its_table():
    query = glossary_query(term(), CATALOG, Engine.POSTGRES)

    assert query == "SELECT status = 'open' FROM public.accounts"


def test_a_table_without_schema_is_in_the_default_one():
    query = glossary_query(term(table="accounts"), CATALOG, Engine.POSTGRES)

    assert query.endswith("FROM public.accounts")


@pytest.mark.parametrize(
    ("sql", "message"),
    [
        ("count(*) FROM salaries --", "not one expression"),
        ("1) UNION SELECT passport FROM clients --", "not one expression"),
        ("status; DROP TABLE accounts", "not one expression"),
        ("balance > (SELECT avg(amount) FROM salaries)", "holds a query"),
        ("status -- passport", "holds a comment"),
        ("/* salaries */ status", "holds a comment"),
    ],
)
def test_an_expression_cannot_reach_beyond_its_table(sql: str, message: str):
    with pytest.raises(KnowledgeError, match=message):
        _ = glossary_query(term(sql), CATALOG, Engine.POSTGRES)


def test_an_unknown_table_is_refused():
    with pytest.raises(KnowledgeError, match="not in the synced schema"):
        _ = glossary_query(term(table="public.loans"), CATALOG, Engine.POSTGRES)


def test_hidden_names_are_those_the_profile_sees_nowhere():
    assert hidden("analyst") == {"passport", "salaries", "amount"}
    # `id` stays: hr sees it in salaries, though not in accounts.
    assert hidden("hr") == {
        "full_name", "passport", "region", "accounts", "client_id", "balance", "status",
    }  # fmt: skip


def test_names_match_as_whole_words_in_any_case():
    names = frozenset({"passport", "salaries", "order date"})

    assert mentions("Needs the PASSPORT number", names) == ["passport"]
    assert mentions("passports and salary", names) == []
    assert mentions("by Order Date", names) == ["order date"]


def test_a_term_is_seen_where_its_expression_passes():
    assert seen(term(), "analyst")
    assert not seen(term(), "hr")


def test_a_term_naming_a_hidden_column_in_words_is_not_seen():
    leaky = term().model_copy(update={"definition": "Open, unlike a passport."})

    assert not seen(leaky, "analyst")


def test_a_term_without_sql_is_seen_unless_it_names_something_hidden():
    plain = GlossaryTerm(term="fiscal year", definition="Starts in April.")
    salaries = GlossaryTerm(term="payroll", definition="What salaries hold.")

    assert seen(plain, "analyst")
    assert seen(plain, "hr")
    assert not seen(salaries, "analyst")
    assert seen(salaries, "hr")


def test_an_example_is_seen_where_its_query_passes():
    example = Example(question="Salaries paid", sql="SELECT sum(amount) FROM salaries")

    assert seen(example, "hr")
    assert not seen(example, "analyst")


def test_an_example_whose_sql_comments_a_hidden_name_is_not_seen():
    example = Example(
        question="Balances",
        sql="SELECT sum(balance) FROM accounts -- see salaries",
    )

    assert not seen(example, "analyst")


def test_without_a_schema_nothing_is_seen():
    blind = Firewall(POLICY)

    reason = why_hidden(
        Example(question="Balances", sql="SELECT sum(balance) FROM accounts"),
        "SELECT sum(balance) FROM accounts",
        firewall=blind,
        connection=CONNECTION,
        profile="analyst",
        hidden=frozenset(),
    )

    assert reason == "there is no synced schema to check it against"


def test_the_reason_names_what_hides_an_entry():
    leaky = GlossaryTerm(term="ids", definition="Kept with the passport.")
    deleting = Example(question="Clean up", sql="DELETE FROM accounts")

    def reason(entry: GlossaryTerm | Example, query: str | None) -> str | None:
        return why_hidden(
            entry,
            query,
            firewall=FIREWALL,
            connection=CONNECTION,
            profile="analyst",
            hidden=hidden("analyst"),
        )

    assert reason(leaky, None) == "it names passport"
    assert (reason(deleting, deleting.sql) or "").startswith("the firewall refuses it:")
