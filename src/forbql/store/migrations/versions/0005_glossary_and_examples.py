"""Glossary terms and examples from the knowledge file, with their vectors.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create both tables; the runtime role replaces their rows at every sync."""
    _ = op.create_table(
        "glossary_terms",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("connection", sa.Text(), nullable=False),
        sa.Column("term", sa.Text(), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("table_name", sa.Text(), nullable=True),
        sa.Column("sql", sa.Text(), nullable=True),
        sa.Column("body_hash", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column(
            "body_tsv",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('simple'::regconfig, term || ' ' || definition)",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column("embedding", Vector(), nullable=False),
        sa.CheckConstraint(
            "(table_name IS NULL) = (sql IS NULL)",
            name="ck_glossary_terms_sql_with_table",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "connection",
            "term",
            name="pk_glossary_terms",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["forbql.workspaces.id"],
            name="fk_glossary_terms_workspace_id",
            ondelete="CASCADE",
        ),
        schema="forbql",
    )
    _ = op.create_table(
        "examples",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("connection", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("sql", sa.Text(), nullable=False),
        sa.Column("body_hash", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column(
            "body_tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple'::regconfig, question)", persisted=True),
            nullable=False,
        ),
        sa.Column("embedding", Vector(), nullable=False),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "connection",
            "question",
            name="pk_examples",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["forbql.workspaces.id"],
            name="fk_examples_workspace_id",
            ondelete="CASCADE",
        ),
        schema="forbql",
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON forbql.glossary_terms TO forbql_app",
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON forbql.examples TO forbql_app")


def downgrade() -> None:
    """Drop both tables."""
    op.drop_table("examples", schema="forbql")
    op.drop_table("glossary_terms", schema="forbql")
