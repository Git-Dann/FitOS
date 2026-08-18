"""Gap aggregate.

Revision ID: 0002
Revises: 0001

The invariants from docs/gap-model.md are CHECK constraints, not service-layer
validation. A rule enforced only in application code can be bypassed by a data
fix, a migration script, or an endpoint written next year — and "no gap without
evidence" is not the kind of rule that tolerates a bypass.

The partial unique index on dedupe_key is what stops one stock discrepancy
pattern becoming thirty near-identical rows. It is partial because a resolved
gap must not block a genuinely new occurrence of the same problem later.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from fitos_api.tenancy_sql import enable_rls, grants_for
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

STATUSES = (
    "detected",
    "triaged",
    "investigating",
    "actioned",
    "validating",
    "resolved",
    "dismissed",
)
SEVERITIES = ("info", "low", "medium", "high", "critical")
UNITS = ("count", "ratio", "currency_minor", "seconds")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.create_table(
        "gaps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pack_key", sa.String(64), nullable=False),
        sa.Column("gap_type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("scope_type", sa.String(32), nullable=False),
        sa.Column("scope_id", sa.String(200), nullable=False),
        sa.Column("metric_definition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_version", sa.Integer, nullable=False),
        sa.Column("observed_value", sa.Numeric, nullable=False),
        sa.Column("expected_value", sa.Numeric, nullable=False),
        sa.Column("absolute_delta", sa.Numeric, nullable=False),
        sa.Column("percentage_delta", sa.Numeric),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("currency", sa.String(3)),
        sa.Column("exposure_low", sa.BigInteger),
        sa.Column("exposure_base", sa.BigInteger),
        sa.Column("exposure_high", sa.BigInteger),
        sa.Column("confidence_score", sa.Numeric(4, 3)),
        sa.Column("confidence_band", sa.String(10)),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="detected"),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True)),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("as_of_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_freshness_seconds", sa.Integer),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule_version", sa.Integer, nullable=False),
        sa.Column("detector_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "assumptions", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("evidence_refs", postgresql.JSONB, nullable=False),
        sa.Column(
            "recommended_actions",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "reason_codes", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("dedupe_key", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("dismissed_at", sa.DateTime(timezone=True)),
        sa.Column("outcome_id", postgresql.UUID(as_uuid=True)),
        sa.CheckConstraint(_in("status", STATUSES), name="ck_gap_status"),
        sa.CheckConstraint(_in("severity", SEVERITIES), name="ck_gap_severity"),
        sa.CheckConstraint(_in("unit", UNITS), name="ck_gap_unit"),
        sa.CheckConstraint(
            "confidence_band IS NULL OR confidence_band IN ('low','medium','high')",
            name="ck_gap_confidence_band",
        ),
        sa.CheckConstraint("jsonb_array_length(evidence_refs) > 0", name="ck_gap_has_evidence"),
        sa.CheckConstraint(
            "(exposure_low IS NULL AND exposure_base IS NULL AND exposure_high IS NULL) "
            "OR (exposure_low IS NOT NULL AND exposure_base IS NOT NULL "
            "AND exposure_high IS NOT NULL)",
            name="ck_gap_exposure_all_or_none",
        ),
        sa.CheckConstraint(
            "exposure_low IS NULL OR "
            "(exposure_low <= exposure_base AND exposure_base <= exposure_high)",
            name="ck_gap_exposure_ordered",
        ),
        sa.CheckConstraint(
            "exposure_base IS NULL OR currency IS NOT NULL", name="ck_gap_exposure_has_currency"
        ),
        sa.CheckConstraint(
            "exposure_base IS NULL OR jsonb_array_length(assumptions) > 0",
            name="ck_gap_exposure_has_assumptions",
        ),
        sa.CheckConstraint(
            "exposure_base IS NULL OR confidence_score IS NOT NULL",
            name="ck_gap_exposure_has_confidence",
        ),
        sa.CheckConstraint(
            "confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)",
            name="ck_gap_confidence_range",
        ),
        sa.CheckConstraint(
            "(status = 'resolved') = (resolved_at IS NOT NULL)", name="ck_gap_resolved_at"
        ),
        sa.CheckConstraint(
            "(status = 'dismissed') = (dismissed_at IS NOT NULL)", name="ck_gap_dismissed_at"
        ),
        sa.CheckConstraint(
            "status <> 'resolved' OR outcome_id IS NOT NULL", name="ck_gap_resolved_has_outcome"
        ),
        sa.CheckConstraint(
            "first_seen_at <= last_seen_at AND last_seen_at <= as_of_at",
            name="ck_gap_timeline_ordered",
        ),
    )
    op.create_index("ix_gaps_org_status", "gaps", ["organization_id", "status"])
    op.create_index("ix_gaps_org_exposure", "gaps", ["organization_id", "exposure_base"])

    # Invariant 6 — one evolving gap per problem, not one per detector run.
    # Partial: a resolved gap must not block a genuine recurrence months later.
    op.execute(
        "CREATE UNIQUE INDEX uq_gap_dedupe_open ON gaps (organization_id, dedupe_key) "
        "WHERE status NOT IN ('resolved', 'dismissed')"
    )

    for statement in enable_rls("gaps"):
        op.execute(statement)
    for statement in grants_for("gaps"):
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("roll forward with a new migration; see 0001")
