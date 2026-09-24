"""The store's tables, in the `forbql` schema; migrations create them."""

from __future__ import annotations

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)

SCHEMA = "forbql"
APP_ROLE = "forbql_app"
"""The runtime role the migrations grant rows to."""
DEFAULT_WORKSPACE = "default"

metadata = MetaData(
    schema=SCHEMA,
    naming_convention={
        "pk": "pk_%(table_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    },
)

workspaces = Table(
    "workspaces",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("name", Text, nullable=False, unique=True),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
)

connections = Table(
    "connections",
    metadata,
    Column("id", Uuid(), primary_key=True, server_default=text("gen_random_uuid()")),
    Column(
        "workspace_id",
        Uuid(),
        ForeignKey(workspaces.c.id, ondelete="CASCADE"),
        nullable=False,
    ),
    Column("name", Text, nullable=False),
    Column("engine", Text, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
    UniqueConstraint("workspace_id", "name"),
    CheckConstraint("engine IN ('postgres', 'mysql', 'sqlite')", name="engine"),
)

connection_secrets = Table(
    "connection_secrets",
    metadata,
    Column(
        "connection_id",
        Uuid(),
        ForeignKey(connections.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
    # Empty for the connection's own DSN; a profile's name for a DSN of its own role.
    Column("profile", Text, primary_key=True),
    Column("key_id", Text, nullable=False),
    Column("sealed", LargeBinary, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
)

audit_records = Table(
    "audit_records",
    metadata,
    Column(
        "workspace_id",
        Uuid(),
        ForeignKey(workspaces.c.id, ondelete="RESTRICT"),
        primary_key=True,
    ),
    Column("seq", BigInteger, primary_key=True),
    Column("at", DateTime(timezone=True), nullable=False),
    Column("principal", Text, nullable=False),
    Column("connection", Text, nullable=False),
    Column("profile", Text, nullable=False),
    Column("policy_hash", Text, nullable=False),
    Column("sql", Text, nullable=False),
    Column("executed_sql", Text),
    Column("allowed", Boolean, nullable=False),
    Column("rules", ARRAY(Text), nullable=False),
    Column("rows", Integer, nullable=False),
    Column("size", BigInteger, nullable=False),
    Column("truncated", Boolean, nullable=False),
    Column("duration_ms", Integer, nullable=False),
    Column("error_class", Text),
    Column("error_detail", Text),
    Column("previous", Text, nullable=False),
    Column("hash", Text, nullable=False),
)

audit_heads = Table(
    "audit_heads",
    metadata,
    Column(
        "workspace_id",
        Uuid(),
        ForeignKey(workspaces.c.id, ondelete="RESTRICT"),
        primary_key=True,
    ),
    Column("seq", BigInteger, nullable=False),
    Column("hash", Text, nullable=False),
)
