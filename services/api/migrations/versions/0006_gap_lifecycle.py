"""Gap lifecycle columns, actions and outcomes.

Revision ID: 0006
Revises: 0005

Three additions, all expand-only.

`gaps.lifecycle_version` is optimistic concurrency for status changes. Two
people triaging the same gap from a stale list would otherwise silently
overwrite each other, and the one who lost would never know. It defaults to 1
for existing rows, which is correct: a gap nobody has transitioned is at
version 1 by definition.

`gaps.dismissal_reason_code` and `dismissal_note` make a dismissal explain
itself. The CHECK ties them to the status rather than leaving it to the service
layer, because dismissal is how a ledger gets quietly emptied and "there is a
code path that sets this" is a weaker promise than "the row cannot exist
otherwise".

`gap_actions` and `gap_outcomes` are separate tables rather than columns on the
gap. A gap can carry several actions, and an outcome has its own measurement
window, method and provenance — flattening either onto the aggregate would
force one action per gap and lose the window.

`gap_outcomes.method` is constrained to `observed`, `pre_post` or
`controlled_test`. The distinction is not bookkeeping: only a `controlled_test`
outcome may use causal language anywhere in the product, and a free-text method
column would make that rule unenforceable.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from fitos_api.tenancy_sql import enable_rls, grants_for
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

LIFECYCLE_TABLES = ("gap_actions", "gap_outcomes")

ACTION_STATUSES = ("open", "in_progress", "done", "cancelled")
OUTCOME_METHODS = ("observed", "pre_post", "controlled_test")

DISMISSAL_REASONS = (
    "not_a_problem",
    "known_and_accepted",
    "duplicate",
    "data_error",
    "out_of_scope",
    "already_fixed",
)


def upgrade() -> None:
    op.add_column(
        "gaps",
        sa.Column("lifecycle_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column("gaps", sa.Column("dismissal_reason_code", sa.String(32)))
    op.add_column("gaps", sa.Column("dismissal_note", sa.Text()))

    op.create_check_constraint("ck_gap_lifecycle_version", "gaps", "lifecycle_version >= 1")
    op.create_check_constraint(
        "ck_gap_dismissal_has_a_reason",
        "gaps",
        "status <> 'dismissed' OR (dismissal_reason_code IS NOT NULL "
        "AND dismissal_note IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_gap_dismissal_reason_known",
        "gaps",
        f"dismissal_reason_code IS NULL OR dismissal_reason_code IN {DISMISSAL_REASONS!r}",
    )

    op.create_table(
        "gap_actions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gap_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("playbook_id", sa.String(120)),
        # Membership id, not user id. Ownership is org-scoped: the same person in
        # two organizations is two assignees, and a user id would let one
        # organization's assignment reference the other's.
        sa.Column("assignee_id", postgresql.UUID(as_uuid=True)),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(f"status IN {ACTION_STATUSES!r}", name="ck_action_status"),
        sa.CheckConstraint(
            "(status = 'done') = (completed_at IS NOT NULL)", name="ck_action_completed_at"
        ),
    )
    op.create_index("ix_gap_actions_org_gap", "gap_actions", ["organization_id", "gap_id"])

    op.create_table(
        "gap_outcomes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gap_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action_id", postgresql.UUID(as_uuid=True)),
        sa.Column("measurement_window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("measurement_window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metric_definition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_version", sa.Integer(), nullable=False),
        sa.Column("value_before", sa.Numeric(), nullable=False),
        sa.Column("value_after", sa.Numeric(), nullable=False),
        sa.Column("delta", sa.Numeric(), nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("recorded_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(f"method IN {OUTCOME_METHODS!r}", name="ck_outcome_method"),
        sa.CheckConstraint(
            "measurement_window_start < measurement_window_end", name="ck_outcome_window_ordered"
        ),
        # An outcome without a metric version cannot be reproduced, which makes
        # it a claim rather than a measurement.
        sa.CheckConstraint("metric_version >= 1", name="ck_outcome_metric_version"),
    )
    op.create_index("ix_gap_outcomes_org_gap", "gap_outcomes", ["organization_id", "gap_id"])

    for statement in enable_rls(*LIFECYCLE_TABLES):
        op.execute(statement)
    for statement in grants_for(*LIFECYCLE_TABLES):
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("roll forward with a new migration; see 0001")
