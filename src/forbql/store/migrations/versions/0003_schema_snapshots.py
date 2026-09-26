"""Snapshots of each connection's schema, one version per sync.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the table; the runtime role may add versions and read them, never edit."""
    _ = op.create_table(
        "schema_snapshots",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("connection", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "taken_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("catalog", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "connection",
            "version",
            name="pk_schema_snapshots",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["forbql.workspaces.id"],
            name="fk_schema_snapshots_workspace_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("version > 0", name="ck_schema_snapshots_version"),
        schema="forbql",
    )
    op.execute("GRANT SELECT, INSERT ON forbql.schema_snapshots TO forbql_app")


def downgrade() -> None:
    """Drop the table."""
    op.drop_table("schema_snapshots", schema="forbql")
