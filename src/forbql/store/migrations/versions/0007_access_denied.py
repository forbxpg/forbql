"""Refused access is a kind of audit record: revoked, expired or ungranted tokens.

Revision 0006 named its check `ck_audit_records_ck_audit_records_action`: the naming
convention prefixed a name that already had the prefix. This one drops it by that
exact name and creates it as the convention means it, `ck_audit_records_action`.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_KINDS = (
    "sql.run",
    "sql.check",
    "schema.search",
    "schema.describe",
    "resource.read",
    "access.denied",
)
"""The kinds of call as this revision knows them."""


def upgrade() -> None:
    """Widen the check to the new kind."""
    op.drop_constraint(
        op.f("ck_audit_records_ck_audit_records_action"),
        "audit_records",
        schema="forbql",
    )
    op.create_check_constraint(
        "action",
        "audit_records",
        f"action IN ({', '.join(f"'{kind}'" for kind in _KINDS)})",
        schema="forbql",
    )


def downgrade() -> None:
    """Narrow the check back; refusals already recorded must be removed first."""
    op.drop_constraint("action", "audit_records", schema="forbql")
    op.create_check_constraint(
        op.f("ck_audit_records_ck_audit_records_action"),
        "audit_records",
        f"action IN ({', '.join(f"'{kind}'" for kind in _KINDS[:-1])})",
        schema="forbql",
    )
