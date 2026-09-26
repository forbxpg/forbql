"""The search index: one document per table and per column, with its vector.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the index table; the runtime role rebuilds it at will.

    pgvector must exist already: only a superuser may create it.

    """
    _ = op.create_table(
        "search_documents",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("connection", sa.Text(), nullable=False),
        sa.Column("table_name", sa.Text(), nullable=False),
        sa.Column("column_name", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("body_hash", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column(
            "body_tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple'::regconfig, body)", persisted=True),
            nullable=False,
        ),
        sa.Column("embedding", Vector(), nullable=False),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "connection",
            "table_name",
            "column_name",
            name="pk_search_documents",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["forbql.workspaces.id"],
            name="fk_search_documents_workspace_id",
            ondelete="CASCADE",
        ),
        schema="forbql",
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON forbql.search_documents TO forbql_app",
    )


def downgrade() -> None:
    """Drop the index table."""
    op.drop_table("search_documents", schema="forbql")
