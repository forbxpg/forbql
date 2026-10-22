"""Generated columns must not copy hidden or stricter columns."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from forbql import Engine, Firewall, RuleId, SchemaSnapshot, Verdict
from forbql.firewall import ColumnInfo, SchemaCatalog, TableInfo
from forbql.policy import parse_policy
from support.firewall import SCHEMA, rules


def _firewall(
    engine: Engine,
    tables_yaml: str,
    tables: dict[str, tuple[str, ...]],
    generated: dict[str, dict[str, str | None]],
) -> Firewall:
    schema = SCHEMA[engine]
    policy = parse_policy(
        f"""
version: 1
connections:
  bank:
    engine: {engine.value}
    profiles:
      analyst:
        tables:
{tables_yaml.format(schema=schema)}
""",
    )
    snapshot = SchemaSnapshot(
        default_schema=schema,
        tables={f"{schema}.{name}": columns for name, columns in tables.items()},
        generated={
            f"{schema}.{name}": expressions for name, expressions in generated.items()
        },
    )
    return Firewall(policy, {"bank": snapshot})


def _check(firewall: Firewall, sql: str) -> Verdict:
    return firewall.check(sql, connection="bank", profile="analyst")


def _quotes(sql: str, column: str) -> bool:
    return f'"{column}"' in sql or f"`{column}`" in sql


def test_selecting_a_generated_copy_of_an_unlisted_column_is_rejected(engine: Engine):
    firewall = _firewall(
        engine,
        """\
          {schema}.gen:
            columns: [id, pub]
""",
        {"gen": ("id", "email", "pub")},
        {"gen": {"pub": "email"}},
    )

    verdict = _check(firewall, "SELECT pub FROM gen")

    assert not verdict.allowed
    assert verdict.sql is None
    assert verdict.masks == ()
    assert rules(verdict) == {RuleId.UNKNOWN_COLUMN}
    assert "email" not in verdict.violations[0].message
    assert "email" not in (verdict.violations[0].hint or "")


def test_star_hides_a_generated_copy_of_a_denied_column(engine: Engine):
    firewall = _firewall(
        engine,
        """\
          {schema}.gen:
            columns: "*"
            pii:
              email: {{ class: deny }}
""",
        {"gen": ("id", "email", "pub")},
        {"gen": {"pub": "email"}},
    )

    selected = _check(firewall, "SELECT pub FROM gen")
    expanded = _check(firewall, "SELECT * FROM gen")

    assert not selected.allowed
    assert selected.sql is None
    assert selected.masks == ()
    assert rules(selected) == {RuleId.UNKNOWN_COLUMN}
    assert "email" not in (selected.violations[0].hint or "")
    assert expanded.allowed
    assert expanded.sql is not None
    assert _quotes(expanded.sql, "id")
    assert not _quotes(expanded.sql, "pub")
    assert not _quotes(expanded.sql, "email")


def test_a_generated_copy_of_a_masked_column_is_rejected(engine: Engine):
    firewall = _firewall(
        engine,
        """\
          {schema}.gen:
            columns: [id, email, pub]
            pii:
              email: {{ class: mask, strategy: redact }}
""",
        {"gen": ("id", "email", "pub")},
        {"gen": {"pub": "email"}},
    )

    verdict = _check(firewall, "SELECT pub FROM gen")
    masked = _check(firewall, "SELECT email FROM gen")

    assert not verdict.allowed
    assert verdict.sql is None
    assert verdict.masks == ()
    assert rules(verdict) == {RuleId.UNKNOWN_COLUMN}
    assert masked.allowed
    assert masked.masks[0].column.endswith(".email")


def test_a_generated_copy_of_an_aggregate_only_column_is_rejected(engine: Engine):
    firewall = _firewall(
        engine,
        """\
          {schema}.gen:
            columns: "*"
            pii:
              email: {{ class: aggregate_only }}
""",
        {"gen": ("id", "email", "pub")},
        {"gen": {"pub": "lower(email)"}},
    )

    verdict = _check(firewall, "SELECT pub FROM gen")

    assert not verdict.allowed
    assert verdict.sql is None
    assert verdict.masks == ()
    assert rules(verdict) == {RuleId.UNKNOWN_COLUMN}


def test_a_generated_column_of_visible_values_stays_visible(engine: Engine):
    firewall = _firewall(
        engine,
        """\
          {schema}.gen:
            columns: [id, label, pub]
""",
        {"gen": ("id", "label", "pub")},
        {"gen": {"pub": "lower(label)"}},
    )

    verdict = _check(firewall, "SELECT pub FROM gen")

    assert verdict.allowed
    assert verdict.sql is not None
    assert _quotes(verdict.sql, "pub")
    assert verdict.masks == ()


def test_an_unreadable_generation_expression_hides_the_column(engine: Engine):
    firewall = _firewall(
        engine,
        """\
          {schema}.gen:
            columns: "*"
""",
        {"gen": ("id", "pub")},
        {"gen": {"pub": None}},
    )

    verdict = _check(firewall, "SELECT pub FROM gen")

    assert not verdict.allowed
    assert verdict.sql is None
    assert rules(verdict) == {RuleId.UNKNOWN_COLUMN}


def test_an_unparseable_generation_expression_hides_the_column(engine: Engine):
    firewall = _firewall(
        engine,
        """\
          {schema}.gen:
            columns: [id, pub]
""",
        {"gen": ("id", "pub")},
        {"gen": {"pub": "((( not sql"}},
    )

    verdict = _check(firewall, "SELECT pub FROM gen")

    assert not verdict.allowed
    assert rules(verdict) == {RuleId.UNKNOWN_COLUMN}


def test_same_table_column_wins_over_another_visible_column(engine: Engine):
    firewall = _firewall(
        engine,
        """\
          {schema}.gen:
            columns: [id, pub]
          {schema}.other:
            columns: [email]
""",
        {"gen": ("id", "email", "pub"), "other": ("email",)},
        {"gen": {"pub": "email"}},
    )

    verdict = _check(firewall, "SELECT pub FROM gen")

    assert not verdict.allowed
    assert rules(verdict) == {RuleId.UNKNOWN_COLUMN}


def test_an_unambiguous_visible_source_keeps_the_generated_column(engine: Engine):
    firewall = _firewall(
        engine,
        """\
          {schema}.gen:
            columns: [id, pub]
          {schema}.other:
            columns: [label]
""",
        {"gen": ("id", "pub"), "other": ("label",)},
        {"gen": {"pub": "other.label"}},
    )

    verdict = _check(firewall, "SELECT pub FROM gen")

    assert verdict.allowed
    assert verdict.masks == ()


def test_an_ambiguous_source_hides_the_generated_column(engine: Engine):
    firewall = _firewall(
        engine,
        """\
          {schema}.gen:
            columns: [id, pub]
          {schema}.a:
            columns: [secret]
""",
        {"gen": ("id", "pub"), "a": ("secret",), "b": ("secret",)},
        {"gen": {"pub": "secret"}},
    )

    verdict = _check(firewall, "SELECT pub FROM gen")

    assert not verdict.allowed
    assert rules(verdict) == {RuleId.UNKNOWN_COLUMN}


def test_a_stricter_source_hides_a_masked_generated_column(engine: Engine):
    firewall = _firewall(
        engine,
        """\
          {schema}.gen:
            columns: "*"
            pii:
              email: {{ class: aggregate_only }}
              pub: {{ class: mask, strategy: redact }}
""",
        {"gen": ("id", "email", "pub")},
        {"gen": {"pub": "email"}},
    )

    verdict = _check(firewall, "SELECT pub FROM gen")

    assert not verdict.allowed
    assert verdict.masks == ()
    assert rules(verdict) == {RuleId.UNKNOWN_COLUMN}


def test_equal_mask_classes_keep_the_generated_column_masked(engine: Engine):
    firewall = _firewall(
        engine,
        """\
          {schema}.gen:
            columns: [email, pub]
            pii:
              email: {{ class: mask, strategy: redact }}
              pub: {{ class: mask, strategy: partial }}
""",
        {"gen": ("email", "pub")},
        {"gen": {"pub": "email"}},
    )

    verdict = _check(firewall, "SELECT pub FROM gen")

    assert verdict.allowed
    assert verdict.masks[0].column.endswith(".pub")


def test_a_generated_column_fed_by_a_hidden_copy_is_hidden(engine: Engine):
    firewall = _firewall(
        engine,
        """\
          {schema}.gen:
            columns: [id, pub, pub2]
""",
        {"gen": ("id", "email", "pub", "pub2")},
        {"gen": {"pub": "email", "pub2": "pub"}},
    )

    assert rules(_check(firewall, "SELECT pub FROM gen")) == {RuleId.UNKNOWN_COLUMN}
    assert rules(_check(firewall, "SELECT pub2 FROM gen")) == {RuleId.UNKNOWN_COLUMN}


def test_catalog_snapshot_copies_generation_expressions():
    catalog = SchemaCatalog(
        default_schema="main",
        tables={
            "main.gen": TableInfo(
                columns=(
                    ColumnInfo(name="id", type="integer", nullable=False),
                    ColumnInfo(name="email", type="text", nullable=True),
                    ColumnInfo(
                        name="pub",
                        type="text",
                        nullable=True,
                        generated=True,
                        expression="email",
                    ),
                    ColumnInfo(
                        name="hidden",
                        type="text",
                        nullable=True,
                        generated=True,
                    ),
                ),
            ),
        },
    )

    assert catalog.snapshot().generated == {
        "main.gen": {"pub": "email", "hidden": None},
    }


def test_within_keeps_expressions_of_columns_that_remain():
    current = SchemaSnapshot(
        default_schema="main",
        tables={"main.gen": ("id", "email", "pub", "old")},
        generated={"main.gen": {"pub": "lower(email)", "old": "email"}},
    )
    reviewed = SchemaSnapshot(
        default_schema="main",
        tables={"main.gen": ("id", "email", "pub")},
        generated={"main.gen": {"pub": "email"}},
    )

    kept = current.within(reviewed)

    assert kept.tables == {"main.gen": ("id", "email", "pub")}
    assert kept.generated == {"main.gen": {"pub": "lower(email)"}}


def test_an_ordinary_column_cannot_carry_an_expression():
    with pytest.raises(ValidationError, match="expression"):
        ColumnInfo(name="id", type="integer", nullable=False, expression="email")
