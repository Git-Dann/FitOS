"""Invitations, and the one sanctioned cross-tenant read.

Revision ID: 0003
Revises: 0002

Two things land together because they are the same flow: joining an
organization, and finding out which organizations you have joined.

The invitation code is a credential and is never stored. Only its SHA-256 is,
which is why `ck_invitation_code_hash_is_a_hash` insists the column looks like
one — a plaintext code written here by a later code path would violate the
constraint rather than sit there quietly.

`user_organizations` is a SECURITY DEFINER function rather than a widened RLS
policy. The reasoning is in tenancy_sql.py, next to the definition.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from fitos_api.tenancy_sql import enable_rls, grants_for, user_organizations_statements
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

ROLES = ("frontline", "manager", "analyst", "admin", "owner", "presenter-demo")
STATUSES = ("pending", "accepted", "revoked", "expired")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.create_table(
        "invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column(
            "granted_capabilities",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("invited_by_membership_id", postgresql.UUID(as_uuid=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True)),
        sa.Column("accepted_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(_in("status", STATUSES), name="ck_invitation_status"),
        sa.CheckConstraint(_in("role", ROLES), name="ck_invitation_role"),
        sa.CheckConstraint(
            "(status = 'accepted') = (accepted_at IS NOT NULL AND accepted_user_id IS NOT NULL)",
            name="ck_invitation_accepted",
        ),
        sa.CheckConstraint(
            "(status = 'revoked') = (revoked_at IS NOT NULL)", name="ck_invitation_revoked"
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_invitation_expiry_future"),
        sa.CheckConstraint(
            "code_hash ~ '^[0-9a-f]{64}$'", name="ck_invitation_code_hash_is_a_hash"
        ),
    )
    op.create_index("ix_invitations_code_hash", "invitations", ["code_hash"])

    # One live invitation per address per organization. Partial, so revoking or
    # letting one expire does not permanently block re-inviting that person.
    op.execute(
        "CREATE UNIQUE INDEX uq_invitation_pending_email "
        "ON invitations (organization_id, email) WHERE status = 'pending'"
    )

    for statement in enable_rls("invitations"):
        op.execute(statement)
    for statement in grants_for("invitations"):
        op.execute(statement)
    for statement in user_organizations_statements():
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("roll forward with a new migration; see 0001")
