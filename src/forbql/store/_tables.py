"""The store's tables, in the `forbql` schema; migrations create them."""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    LargeBinary,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR

from forbql.audit import Action

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
    Column("action", Text, nullable=False),
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
    CheckConstraint(
        "action IN (" + ", ".join(f"'{action}'" for action in Action) + ")",
        name="action",
    ),
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

tokens = Table(
    "tokens",
    metadata,
    Column("id", Text, primary_key=True),
    Column(
        "workspace_id",
        Uuid(),
        ForeignKey(workspaces.c.id, ondelete="CASCADE"),
        nullable=False,
    ),
    Column("name", Text, nullable=False),
    Column("secret_hash", Text, nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    UniqueConstraint("workspace_id", "name"),
    CheckConstraint("id ~ '^[0-9a-f]{12}$'", name="id"),
    CheckConstraint("expires_at > created_at", name="expiry"),
)

token_grants = Table(
    "token_grants",
    metadata,
    Column(
        "token_id",
        Text,
        ForeignKey(tokens.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("connection", Text, primary_key=True),
    Column("profile", Text, primary_key=True),
    Column("capabilities", ARRAY(Text), nullable=False),
    CheckConstraint(
        (
            "cardinality(capabilities) > 0 AND capabilities <@ ARRAY["
            "'schema.read', 'sql.check', 'sql.run', 'knowledge.propose']::text[]"
        ),
        name="capabilities",
    ),
)

schema_snapshots = Table(
    "schema_snapshots",
    metadata,
    Column(
        "workspace_id",
        Uuid(),
        ForeignKey(workspaces.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("connection", Text, primary_key=True),
    Column("version", Integer, primary_key=True),
    Column(
        "taken_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
    Column("content_hash", Text, nullable=False),
    Column("catalog", JSONB(), nullable=False),
    CheckConstraint("version > 0", name="version"),
)

search_documents = Table(
    "search_documents",
    metadata,
    Column(
        "workspace_id",
        Uuid(),
        ForeignKey(workspaces.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("connection", Text, primary_key=True),
    Column("table_name", Text, primary_key=True),
    # Empty for the table's own document.
    Column("column_name", Text, primary_key=True),
    Column("body", Text, nullable=False),
    Column("body_hash", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column(
        "body_tsv",
        TSVECTOR(),
        Computed("to_tsvector('simple'::regconfig, body)", persisted=True),
        nullable=False,
    ),
    Column("embedding", Vector(), nullable=False),
)

glossary_terms = Table(
    "glossary_terms",
    metadata,
    Column(
        "workspace_id",
        Uuid(),
        ForeignKey(workspaces.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("connection", Text, primary_key=True),
    Column("term", Text, primary_key=True),
    Column("definition", Text, nullable=False),
    # Both empty for a term the schema cannot express.
    Column("table_name", Text),
    Column("sql", Text),
    Column("body_hash", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column(
        "body_tsv",
        TSVECTOR(),
        Computed(
            "to_tsvector('simple'::regconfig, term || ' ' || definition)",
            persisted=True,
        ),
        nullable=False,
    ),
    Column("embedding", Vector(), nullable=False),
    CheckConstraint(
        "(table_name IS NULL) = (sql IS NULL)",
        name="sql_with_table",
    ),
)

example_proposals = Table(
    "example_proposals",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column(
        "workspace_id",
        Uuid(),
        ForeignKey(workspaces.c.id, ondelete="CASCADE"),
        nullable=False,
    ),
    Column("connection", Text, nullable=False),
    # The proposer's profile: approval checks the example under it again.
    Column("profile", Text, nullable=False),
    Column("question", Text, nullable=False),
    Column("sql", Text, nullable=False),
    # `token:<id>` over HTTP, `local:<user>` over stdio.
    Column("author", Text, nullable=False),
    Column(
        "proposed_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    ),
    Column("approved_by", Text),
    Column("approved_at", DateTime(timezone=True)),
    UniqueConstraint("workspace_id", "connection", "question"),
    CheckConstraint("(approved_by IS NULL) = (approved_at IS NULL)", name="approval"),
)

examples = Table(
    "examples",
    metadata,
    Column(
        "workspace_id",
        Uuid(),
        ForeignKey(workspaces.c.id, ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("connection", Text, primary_key=True),
    Column("question", Text, primary_key=True),
    Column("sql", Text, nullable=False),
    Column("body_hash", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column(
        "body_tsv",
        TSVECTOR(),
        Computed("to_tsvector('simple'::regconfig, question)", persisted=True),
        nullable=False,
    ),
    Column("embedding", Vector(), nullable=False),
    # Empty for an example from the knowledge file; rejecting the proposal drops it.
    Column(
        "proposal_id",
        BigInteger,
        ForeignKey(example_proposals.c.id, ondelete="CASCADE"),
    ),
)
