"""Workspaces, connections with sealed DSNs, and the audit chain.

Revision ID: 0001
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_GENESIS = "0" * 64


def upgrade() -> None:
    """Create the tables, the default workspace, and the runtime role's rights."""
    _ = op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workspaces"),
        sa.UniqueConstraint("name", name="uq_workspaces_name"),
        schema="forbql",
    )
    _ = op.create_table(
        "connections",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("engine", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_connections"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["forbql.workspaces.id"],
            name="fk_connections_workspace_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "name",
            name="uq_connections_workspace_id_name",
        ),
        sa.CheckConstraint(
            "engine IN ('postgres', 'mysql', 'sqlite')",
            name="ck_connections_engine",
        ),
        schema="forbql",
    )
    _ = op.create_table(
        "connection_secrets",
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("profile", sa.Text(), nullable=False),
        sa.Column("key_id", sa.Text(), nullable=False),
        sa.Column("sealed", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "connection_id",
            "profile",
            name="pk_connection_secrets",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["forbql.connections.id"],
            name="fk_connection_secrets_connection_id",
            ondelete="CASCADE",
        ),
        schema="forbql",
    )
    _ = op.create_table(
        "audit_records",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("principal", sa.Text(), nullable=False),
        sa.Column("connection", sa.Text(), nullable=False),
        sa.Column("profile", sa.Text(), nullable=False),
        sa.Column("policy_hash", sa.Text(), nullable=False),
        sa.Column("sql", sa.Text(), nullable=False),
        sa.Column("executed_sql", sa.Text(), nullable=True),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("rules", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("rows", sa.Integer(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("error_class", sa.Text(), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("previous", sa.Text(), nullable=False),
        sa.Column("hash", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "seq", name="pk_audit_records"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["forbql.workspaces.id"],
            name="fk_audit_records_workspace_id",
            ondelete="RESTRICT",
        ),
        schema="forbql",
    )
    _ = op.create_table(
        "audit_heads",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("hash", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", name="pk_audit_heads"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["forbql.workspaces.id"],
            name="fk_audit_heads_workspace_id",
            ondelete="RESTRICT",
        ),
        schema="forbql",
    )
    op.execute("INSERT INTO forbql.workspaces (name) VALUES ('default')")
    op.execute(
        sa.text(
            """
            INSERT INTO forbql.audit_heads (workspace_id, seq, hash)
            SELECT id, 0, :genesis FROM forbql.workspaces
            """,
        ).bindparams(genesis=_GENESIS),
    )
    # The runtime role writes rows and nothing else; the audit chain only grows.
    for grant in (
        "GRANT USAGE ON SCHEMA forbql TO forbql_app",
        "GRANT SELECT ON forbql.workspaces, forbql.alembic_version TO forbql_app",
        (
            "GRANT SELECT, INSERT, UPDATE, DELETE "
            "ON forbql.connections, forbql.connection_secrets TO forbql_app"
        ),
        "GRANT SELECT, INSERT ON forbql.audit_records TO forbql_app",
        "GRANT SELECT, UPDATE ON forbql.audit_heads TO forbql_app",
    ):
        op.execute(grant)


def downgrade() -> None:
    """Drop everything the upgrade created."""
    for table in (
        "audit_heads",
        "audit_records",
        "connection_secrets",
        "connections",
        "workspaces",
    ):
        op.drop_table(table, schema="forbql")
