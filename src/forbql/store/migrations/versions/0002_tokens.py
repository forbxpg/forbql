"""Tokens and their grants.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the tables; a revoked token stays revoked, a secret hash never changes."""
    _ = op.create_table(
        "tokens",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("secret_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_tokens"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["forbql.workspaces.id"],
            name="fk_tokens_workspace_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("workspace_id", "name", name="uq_tokens_workspace_id_name"),
        sa.CheckConstraint("id ~ '^[0-9a-f]{12}$'", name="ck_tokens_id"),
        sa.CheckConstraint("expires_at > created_at", name="ck_tokens_expiry"),
        schema="forbql",
    )
    _ = op.create_table(
        "token_grants",
        sa.Column("token_id", sa.Text(), nullable=False),
        sa.Column("connection", sa.Text(), nullable=False),
        sa.Column("profile", sa.Text(), nullable=False),
        sa.Column("capabilities", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint(
            "token_id",
            "connection",
            "profile",
            name="pk_token_grants",
        ),
        sa.ForeignKeyConstraint(
            ["token_id"],
            ["forbql.tokens.id"],
            name="fk_token_grants_token_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            (
                "cardinality(capabilities) > 0 AND capabilities <@ ARRAY["
                "'schema.read', 'sql.check', 'sql.run', 'knowledge.propose']::text[]"
            ),
            name="ck_token_grants_capabilities",
        ),
        schema="forbql",
    )
    op.execute("""
        CREATE FUNCTION forbql.tokens_stay_revoked() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.revoked_at IS NOT NULL
               AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
                RAISE EXCEPTION 'a revoked token stays revoked';
            END IF;
            RETURN NEW;
        END
        $$
    """)
    op.execute("""
        CREATE TRIGGER tokens_stay_revoked BEFORE UPDATE ON forbql.tokens
        FOR EACH ROW EXECUTE FUNCTION forbql.tokens_stay_revoked()
    """)
    # The runtime role issues and revokes, and changes nothing else.
    for grant in (
        "GRANT SELECT, INSERT ON forbql.tokens, forbql.token_grants TO forbql_app",
        "GRANT UPDATE (revoked_at) ON forbql.tokens TO forbql_app",
    ):
        op.execute(grant)


def downgrade() -> None:
    """Drop everything the upgrade created."""
    op.drop_table("token_grants", schema="forbql")
    op.drop_table("tokens", schema="forbql")
    op.execute("DROP FUNCTION forbql.tokens_stay_revoked()")
