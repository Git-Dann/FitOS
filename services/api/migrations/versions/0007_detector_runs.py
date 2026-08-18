"""Detector run records.

Revision ID: 0007
Revises: 0006

Every detector run writes one of these, whether it found anything or not. The
acceptance criterion names the contents: versions, query hash, window,
thresholds, candidates, suppressions, dedupe decisions, duration and errors.

`readings_considered` and `insufficient_readings` are stored separately because
a run that examined four hundred readings and refused three hundred and
ninety-nine for thin samples is otherwise indistinguishable from a clean run
that found nothing. Both produce zero gaps; only one of them means the estate
is fine.

No DELETE, for the same reason `audit_events` has none. A run record you can
remove is a run record that cannot answer "why did this gap stop firing".
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from fitos_api.tenancy_sql import enable_rls, grants_for
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

TABLES = ("detector_runs",)


def upgrade() -> None:
    op.create_table(
        "detector_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("detector_key", sa.String(64), nullable=False),
        sa.Column("pack_key", sa.String(64), nullable=False),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        # Hash of the effective configuration. Makes "the threshold changed" a
        # checkable event rather than something inferred from a gap that
        # stopped firing.
        sa.Column("config_fingerprint", sa.String(64), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("readings_considered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("insufficient_readings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candidates_produced", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("candidates_suppressed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("gaps_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("gaps_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correlations_linked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "query_hashes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "dedupe_decisions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "thresholds", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "errors", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("skipped_reason", sa.Text()),
        sa.CheckConstraint("window_start < window_end", name="ck_detector_run_window_ordered"),
        sa.CheckConstraint("duration_ms >= 0", name="ck_detector_run_duration"),
        # A run cannot have produced fewer readings than it refused.
        sa.CheckConstraint(
            "insufficient_readings <= readings_considered",
            name="ck_detector_run_refusals_within_readings",
        ),
    )
    op.create_index(
        "ix_detector_runs_org_time", "detector_runs", ["organization_id", "finished_at"]
    )
    op.create_index(
        "ix_detector_runs_org_rule", "detector_runs", ["organization_id", "rule_id", "rule_version"]
    )

    for statement in enable_rls(*TABLES):
        op.execute(statement)
    for statement in grants_for(*TABLES):
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("roll forward with a new migration; see 0001")
