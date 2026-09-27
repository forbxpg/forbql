"""Every audit record names its kind of call: queries, searches, descriptions, reads.

Records written before this revision were all queries; they become `sql.run`. Their
hashes did not cover the new field, so `audit verify` reports a chain begun before this
revision as broken: v0.1 keeps no compatibility with pre-release chains.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_KINDS = ("sql.run", "sql.check", "schema.search", "schema.describe", "resource.read")
"""The kinds of call as this revision knows them; later ones widen the list."""


def upgrade() -> None:
    """Add the column, fill it for old records, and keep it to the known kinds."""
    op.add_column(
        "audit_records",
        sa.Column("action", sa.Text(), nullable=False, server_default="sql.run"),
        schema="forbql",
    )
    op.alter_column("audit_records", "action", server_default=None, schema="forbql")
    op.create_check_constraint(
        "ck_audit_records_action",
        "audit_records",
        f"action IN ({', '.join(f"'{kind}'" for kind in _KINDS)})",
        schema="forbql",
    )


def downgrade() -> None:
    """Drop the column and its constraint."""
    op.drop_constraint("ck_audit_records_action", "audit_records", schema="forbql")
    op.drop_column("audit_records", "action", schema="forbql")
