"""Examples agents propose, waiting for the operator; approved ones join the rest.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_KINDS = (
    "sql.run",
    "sql.check",
    "schema.search",
    "schema.describe",
    "resource.read",
    "access.denied",
    "knowledge.propose",
    "knowledge.approve",
    "knowledge.reject",
)
"""The kinds of call as this revision knows them."""

_BEFORE = 6
"""How many of them revision 0007 knew."""


def upgrade() -> None:
    """Create the queue, point examples at it, and admit the three new kinds."""
    _ = op.create_table(
        "example_proposals",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("connection", sa.Text(), nullable=False),
        sa.Column("profile", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("sql", sa.Text(), nullable=False),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column(
            "proposed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("approved_by", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(approved_by IS NULL) = (approved_at IS NULL)",
            name=op.f("ck_example_proposals_approval"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_example_proposals")),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["forbql.workspaces.id"],
            name=op.f("fk_example_proposals_workspace_id"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "connection",
            "question",
            name=op.f("uq_example_proposals_workspace_id_connection_question"),
        ),
        schema="forbql",
    )
    op.add_column(
        "examples",
        sa.Column("proposal_id", sa.BigInteger(), nullable=True),
        schema="forbql",
    )
    op.create_foreign_key(
        op.f("fk_examples_proposal_id"),
        "examples",
        "example_proposals",
        ["proposal_id"],
        ["id"],
        source_schema="forbql",
        referent_schema="forbql",
        ondelete="CASCADE",
    )
    grant = "GRANT SELECT, INSERT, UPDATE, DELETE ON forbql.example_proposals"
    op.execute(f"{grant} TO forbql_app")
    _widen(_KINDS)


def downgrade() -> None:
    """Drop the queue; records of the new kinds must be removed first."""
    _widen(_KINDS[:_BEFORE])
    op.drop_constraint(
        op.f("fk_examples_proposal_id"),
        "examples",
        schema="forbql",
        type_="foreignkey",
    )
    op.drop_column("examples", "proposal_id", schema="forbql")
    op.drop_table("example_proposals", schema="forbql")


def _widen(kinds: tuple[str, ...]) -> None:
    """Keep audit records to these kinds of call.

    Args:
        kinds: tuple[str, ...] - The kinds.

    """
    op.drop_constraint(
        op.f("ck_audit_records_action"),
        "audit_records",
        schema="forbql",
    )
    op.create_check_constraint(
        op.f("ck_audit_records_action"),
        "audit_records",
        f"action IN ({', '.join(f"'{kind}'" for kind in kinds)})",
        schema="forbql",
    )
