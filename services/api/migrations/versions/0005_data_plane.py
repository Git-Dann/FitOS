"""Connections, mapping versions, runs, quarantine and webhook deliveries.

Revision ID: 0005
Revises: 0004

The control tables for the data plane. Four of the five are records of what
happened rather than mutable state, and are granted no DELETE for the same
reason `audit_events` is not: a record you can delete is a record you cannot
rely on when somebody asks why a number changed.

Two protections here cannot be expressed as CHECK constraints and are triggers:

`mapping_versions_freeze_applied` — a version that has been applied is frozen
except for `is_active`. A CHECK sees one row at a time and cannot compare the
old values with the new ones, so it cannot express "this column must not
change". Without it, a correction could be made by editing the mapping that
produced the numbers people already acted on, and the canonical rows it created
would no longer be reproducible.

`connector_runs_no_count_rewrite` — a finished run's counts are final. The
temptation is to "tidy up" a rejected count after the fact, which is precisely
what makes the count untrustworthy.

`webhook_deliveries` is release gate 8 as a table. The unique constraint is the
mechanism, not a safety net: check-then-insert is a race two workers lose
together, and the duplicate the check existed to prevent happens anyway.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from fitos_api.tenancy_sql import data_plane_trigger_statements, enable_rls, grants_for
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

STATUSES = (
    "configured",
    "testing",
    "syncing",
    "healthy",
    "delayed",
    "schema_changed",
    "failed",
    "disabled",
    "fixture",
)
OUTCOMES = ("running", "succeeded", "partial", "failed")
TRIGGERS = ("manual", "schedule", "webhook", "backfill")

DATA_PLANE_TABLES = (
    "connections",
    "mapping_versions",
    "connector_runs",
    "quarantined_records",
    "webhook_deliveries",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("connector_key", sa.String(64), nullable=False),
        sa.Column("connector_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "config", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="configured"),
        sa.Column("is_fixture", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("last_successful_run_at", sa.DateTime(timezone=True)),
        sa.Column("expected_cadence_seconds", sa.Integer),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("organization_id", "name", name="uq_connection_org_name"),
        sa.CheckConstraint(_in("status", STATUSES), name="ck_connection_status"),
        sa.CheckConstraint(
            "NOT (is_fixture AND status = 'healthy')", name="ck_connection_fixture_is_not_healthy"
        ),
        # Secrets belong in the secret manager. A config carrying one would put
        # it in every backup and every support export of this table.
        sa.CheckConstraint(
            "NOT (config::text ~* '(password|secret|token|api[_-]?key|private[_-]?key)')",
            name="ck_connection_config_has_no_secrets",
        ),
    )
    op.create_index("ix_connections_org", "connections", ["organization_id"])

    op.create_table(
        "mapping_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("resource", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("column_map", postgresql.JSONB, nullable=False),
        sa.Column(
            "required_columns",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "transforms", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("target_table", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_membership_id", postgresql.UUID(as_uuid=True)),
        sa.Column("note", sa.Text),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "connection_id", "resource", "version", name="uq_mapping_connection_resource_version"
        ),
        sa.CheckConstraint("version >= 1", name="ck_mapping_version_positive"),
        sa.CheckConstraint(
            "jsonb_typeof(column_map) = 'object' AND column_map <> '{}'::jsonb",
            name="ck_mapping_has_columns",
        ),
        sa.CheckConstraint(
            "is_active = (applied_at IS NOT NULL)", name="ck_mapping_active_applied"
        ),
    )
    op.create_index("ix_mapping_versions_org", "mapping_versions", ["organization_id"])
    # Exactly one live mapping per resource. Two would mean two answers to
    # "how was this row produced", which makes lineage meaningless.
    op.execute(
        "CREATE UNIQUE INDEX uq_mapping_one_active_per_resource "
        "ON mapping_versions (connection_id, resource) WHERE is_active"
    )

    op.create_table(
        "connector_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("connector_key", sa.String(64), nullable=False),
        sa.Column("connector_version", sa.Integer, nullable=False),
        sa.Column("mapping_version", sa.Integer),
        sa.Column("trigger", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("outcome", sa.String(16), nullable=False, server_default="running"),
        sa.Column("records_read", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("records_written", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("records_quarantined", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("rate_limit_waits", sa.Integer, nullable=False, server_default="0"),
        sa.Column("retries", sa.Integer, nullable=False, server_default="0"),
        sa.Column("checkpoint", postgresql.JSONB),
        sa.Column(
            "resources", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column(
            "secrets_used", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("error", sa.Text),
        sa.Column("trace_id", sa.String(64)),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(_in("outcome", OUTCOMES), name="ck_run_outcome"),
        sa.CheckConstraint(_in("trigger", TRIGGERS), name="ck_run_trigger"),
        sa.CheckConstraint(
            "records_read >= 0 AND records_written >= 0 AND records_quarantined >= 0",
            name="ck_run_counts_non_negative",
        ),
        sa.CheckConstraint(
            "(outcome = 'running') = (finished_at IS NULL)", name="ck_run_finished_at"
        ),
        sa.CheckConstraint(
            "outcome <> 'failed' OR error IS NOT NULL", name="ck_run_failed_has_error"
        ),
    )
    op.create_index("ix_runs_org_started", "connector_runs", ["organization_id", "started_at"])
    op.create_index("ix_runs_connection", "connector_runs", ["connection_id", "started_at"])

    op.create_table(
        "quarantined_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("connector_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("connector_key", sa.String(64), nullable=False),
        sa.Column("resource", sa.String(64), nullable=False),
        sa.Column("source_record_id", sa.String(400), nullable=False),
        sa.Column("raw_ref", sa.Text, nullable=False),
        sa.Column("mapping_version", sa.Integer, nullable=False),
        sa.Column("reasons", postgresql.JSONB, nullable=False),
        sa.Column(
            "payload", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column(
            "quarantined_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("jsonb_array_length(reasons) > 0", name="ck_quarantine_has_reason"),
        sa.CheckConstraint("raw_ref <> ''", name="ck_quarantine_has_raw_ref"),
    )
    op.create_index("ix_quarantine_org_run", "quarantined_records", ["organization_id", "run_id"])
    op.create_index(
        "ix_quarantine_org_time", "quarantined_records", ["organization_id", "quarantined_at"]
    )

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("connector_key", sa.String(64), nullable=False),
        sa.Column("delivery_id", sa.String(200), nullable=False),
        sa.Column("raw_ref", sa.Text),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "organization_id", "connector_key", "delivery_id", name="uq_webhook_delivery_once"
        ),
    )
    op.create_index(
        "ix_webhook_deliveries_org_time", "webhook_deliveries", ["organization_id", "received_at"]
    )

    # Triggers come from tenancy_sql so the migration and the metadata-built
    # test schema apply the same definition. A trigger that exists only here is
    # a trigger the tests cannot prove.
    for statement in data_plane_trigger_statements():
        op.execute(statement)

    for statement in enable_rls(*DATA_PLANE_TABLES):
        op.execute(statement)
    for statement in grants_for(*DATA_PLANE_TABLES):
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("roll forward with a new migration; see 0001")
