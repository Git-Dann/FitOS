"""Tenancy, capabilities and audit.

Revision ID: 0001
Revises:
Create Date: Phase B

Creates the control-plane tables and applies row-level security in the same
migration. Not in a follow-up: "add RLS later" is how a table ships without it,
and a table without a policy is readable across tenants.

Expand-migrate-contract applies from here on. This is the first migration, so
there is nothing to contract.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from fitos_api.tenancy_sql import APP_ROLE, create_roles, enable_rls, grants_for
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

ROLES = ("frontline", "manager", "analyst", "admin", "owner", "presenter-demo")


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("is_demo", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "display_timezone", sa.String(64), nullable=False, server_default="Europe/London"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$'", name="ck_org_slug_format"),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("display_name", sa.String(200)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column(
            "granted_capabilities",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_membership_org_user"),
        sa.CheckConstraint(
            "role IN (" + ", ".join(f"'{r}'" for r in ROLES) + ")", name="ck_membership_role"
        ),
    )
    op.create_index("ix_memberships_org", "memberships", ["organization_id"])

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_membership_id", postgresql.UUID(as_uuid=True)),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("object_type", sa.String(100), nullable=False),
        sa.Column("object_id", sa.String(200), nullable=False),
        sa.Column("before", postgresql.JSONB),
        sa.Column("after", postgresql.JSONB),
        sa.Column("reason", sa.Text),
        sa.Column("request_id", sa.String(64)),
        sa.Column("trace_id", sa.String(64)),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_audit_org_time", "audit_events", ["organization_id", "occurred_at"])

    # Roles, grants and policies. The password is supplied by the environment;
    # there is no default, because a default password in a migration becomes a
    # production password.
    import os

    app_password = os.environ.get("FITOS_APP_ROLE_PASSWORD")
    if not app_password:
        raise RuntimeError(
            "FITOS_APP_ROLE_PASSWORD must be set to create the application role. "
            "It is never defaulted: a default here becomes a production credential."
        )
    for statement in create_roles(app_password):
        op.execute(statement)
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON organizations, users TO {APP_ROLE};")
    for statement in grants_for("memberships", "audit_events"):
        op.execute(statement)
    for statement in enable_rls("organizations", "memberships", "audit_events"):
        op.execute(statement)


def downgrade() -> None:
    # Deliberately not implemented. Dropping these tables destroys the audit
    # trail, which is exactly what T13 says must not be possible. Roll forward
    # with a new migration instead (CLAUDE.md, expand-migrate-contract).
    raise NotImplementedError(
        "downgrade would destroy the audit trail; write a forward migration instead"
    )
