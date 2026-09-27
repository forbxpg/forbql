"""CHECK constraints take the names the models give them.

Revisions 0001 to 0005 passed full names to a metadata whose naming convention prefixes
them again, so the store holds `ck_connections_ck_connections_engine` where the models
name `ck_connections_engine`. Revision 0007 already rebuilt the audit records' one.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_CHECKS = (
    ("connections", "engine"),
    ("tokens", "id"),
    ("tokens", "expiry"),
    ("token_grants", "capabilities"),
    ("schema_snapshots", "version"),
    ("glossary_terms", "sql_with_table"),
)
"""Each doubled constraint as its table and the name the models give it."""


def _rename(table: str, old: str, new: str) -> None:
    """Rename a constraint in place; raw SQL, so no naming convention touches the names.

    Args:
        table: str - Table in the `forbql` schema.
        old: str - The constraint's current name.
        new: str - Its new name.

    """
    op.execute(f"ALTER TABLE forbql.{table} RENAME CONSTRAINT {old} TO {new}")


def upgrade() -> None:
    """Drop the doubled prefix from each constraint."""
    for table, name in _CHECKS:
        _rename(table, f"ck_{table}_ck_{table}_{name}", f"ck_{table}_{name}")


def downgrade() -> None:
    """Double the prefix again, as revisions 0001 to 0005 built it."""
    for table, name in _CHECKS:
        _rename(table, f"ck_{table}_{name}", f"ck_{table}_ck_{table}_{name}")
