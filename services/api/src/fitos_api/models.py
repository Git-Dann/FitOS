"""Control-plane tables.

Phase B covers tenancy and audit only. Gaps, actions and outcomes arrive in
Phase D; sources and mappings in Phase C. Every table that carries
`organization_id` gets RLS in the same migration that creates it — not later,
because "add RLS afterwards" is how a table ships without it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Destructive demo commands refuse any tenant without this flag
    # (CLAUDE.md, "Destructive commands").
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    display_timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="Europe/London"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$'", name="ck_org_slug_format"),
    )


class User(Base):
    """Identity mirror.

    Better Auth owns the credential; this row exists so memberships have
    something to hang off and so the audit log can name an actor. It carries
    no password, no session and no token.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Membership(Base):
    """A user's role within one organization.

    Ownership elsewhere in the product references membership, not user: a
    person can belong to two organizations with different roles, and "who owns
    this gap" is only meaningful inside an organization.
    """

    __tablename__ = "memberships"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    # Per-organization capability grants, e.g. giving frontline gap.view_exposure
    # where there is a documented need. Empty for almost every membership.
    granted_capabilities: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_membership_org_user"),
        CheckConstraint(
            "role IN ('frontline','manager','analyst','admin','owner','presenter-demo')",
            name="ck_membership_role",
        ),
        Index("ix_memberships_org", "organization_id"),
    )


class Invitation(Base):
    """An offer of membership, redeemable once.

    The invitation code is a credential, so the code itself is never stored —
    only `code_hash`, a SHA-256 of the secret half (CLAUDE.md: no secrets in
    application tables). A leaked database backup therefore yields no usable
    invitation. The code is shown exactly once, in the response to the request
    that created it, and cannot be retrieved afterwards.

    The code the recipient receives is `<organization_id>.<secret>`. The
    organization half is not authority — it is there so the API can open the
    tenant scope *before* looking the invitation up, which keeps redemption
    inside RLS instead of needing an exemption to find the row. The secret half
    is what actually proves anything.

    Status is a column rather than a computed property because expiry and
    revocation must be visible to a query and to the audit trail, not inferred
    at read time by whichever caller happens to look.
    """

    __tablename__ = "invitations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    granted_capabilities: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    invited_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked', 'expired')",
            name="ck_invitation_status",
        ),
        CheckConstraint(
            "role IN ('frontline', 'manager', 'analyst', 'admin', 'owner', 'presenter-demo')",
            name="ck_invitation_role",
        ),
        # An accepted invitation names who accepted it and when; an unaccepted
        # one names neither. Half-recorded acceptance is not a state the audit
        # trail should be able to reach.
        CheckConstraint(
            "(status = 'accepted') = (accepted_at IS NOT NULL AND accepted_user_id IS NOT NULL)",
            name="ck_invitation_accepted",
        ),
        CheckConstraint(
            "(status = 'revoked') = (revoked_at IS NOT NULL)", name="ck_invitation_revoked"
        ),
        CheckConstraint("expires_at > created_at", name="ck_invitation_expiry_future"),
        CheckConstraint("code_hash ~ '^[0-9a-f]{64}$'", name="ck_invitation_code_hash_is_a_hash"),
        # One live invitation per address per organization. Partial, so a
        # revoked or expired invitation does not block re-inviting someone.
        Index(
            "uq_invitation_pending_email",
            "organization_id",
            "email",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_invitations_code_hash", "code_hash"),
    )


class AuditEvent(Base):
    """Append-only.

    The application database role is granted INSERT and SELECT only. An
    attempted UPDATE or DELETE fails at the database, not at a code path that
    could be bypassed (docs/threat-model.md T13).
    """

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    actor_membership_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    object_type: Mapped[str] = mapped_column(String(100), nullable=False)
    object_id: Mapped[str] = mapped_column(String(200), nullable=False)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(String(64))
    trace_id: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_audit_org_time", "organization_id", "occurred_at"),)


# ---------------------------------------------------------------------------
# Gaps
#
# The invariants in docs/gap-model.md are enforced as CHECK constraints, not as
# service-layer validation. A rule that lives only in application code is a rule
# that a migration script, a data fix or a future endpoint can bypass — and
# "no gap without evidence" is not a guideline.
# ---------------------------------------------------------------------------

GAP_STATUSES = (
    "detected",
    "triaged",
    "investigating",
    "actioned",
    "validating",
    "resolved",
    "dismissed",
)
TERMINAL_STATUSES = ("resolved", "dismissed")
SEVERITIES = ("info", "low", "medium", "high", "critical")
CONFIDENCE_BANDS = ("low", "medium", "high")
UNITS = ("count", "ratio", "currency_minor", "seconds")


class Gap(Base):
    __tablename__ = "gaps"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    pack_key: Mapped[str] = mapped_column(String(64), nullable=False)
    gap_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)

    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(200), nullable=False)

    # The *primary* metric. Contributing metrics live in evidence_refs — see
    # docs/spec-review.md R4.
    metric_definition_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    metric_version: Mapped[int] = mapped_column(Integer, nullable=False)

    observed_value: Mapped[float] = mapped_column(Numeric, nullable=False)
    expected_value: Mapped[float] = mapped_column(Numeric, nullable=False)
    absolute_delta: Mapped[float] = mapped_column(Numeric, nullable=False)
    percentage_delta: Mapped[float | None] = mapped_column(Numeric)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(3))

    exposure_low: Mapped[int | None] = mapped_column(BigInteger)
    exposure_base: Mapped[int | None] = mapped_column(BigInteger)
    exposure_high: Mapped[int | None] = mapped_column(BigInteger)

    confidence_score: Mapped[float | None] = mapped_column(Numeric(4, 3))
    confidence_band: Mapped[str | None] = mapped_column(String(10))
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="detected")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    as_of_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_freshness_seconds: Mapped[int | None] = mapped_column(Integer)

    rule_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    detector_run_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)

    assumptions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    evidence_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    recommended_actions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    reason_codes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    dedupe_key: Mapped[str] = mapped_column(String(128), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))

    __table_args__ = (
        CheckConstraint(f"status IN {GAP_STATUSES!r}", name="ck_gap_status"),
        CheckConstraint(f"severity IN {SEVERITIES!r}", name="ck_gap_severity"),
        CheckConstraint(f"unit IN {UNITS!r}", name="ck_gap_unit"),
        CheckConstraint(
            "confidence_band IS NULL OR confidence_band IN ('low','medium','high')",
            name="ck_gap_confidence_band",
        ),
        # Invariant 1 — no gap without evidence.
        CheckConstraint("jsonb_array_length(evidence_refs) > 0", name="ck_gap_has_evidence"),
        # Invariant 2 — modelled money is a range with assumptions, or absent.
        CheckConstraint(
            "(exposure_low IS NULL AND exposure_base IS NULL AND exposure_high IS NULL) "
            "OR (exposure_low IS NOT NULL AND exposure_base IS NOT NULL "
            "AND exposure_high IS NOT NULL)",
            name="ck_gap_exposure_all_or_none",
        ),
        CheckConstraint(
            "exposure_low IS NULL OR (exposure_low <= exposure_base "
            "AND exposure_base <= exposure_high)",
            name="ck_gap_exposure_ordered",
        ),
        CheckConstraint(
            "exposure_base IS NULL OR currency IS NOT NULL", name="ck_gap_exposure_has_currency"
        ),
        CheckConstraint(
            "exposure_base IS NULL OR jsonb_array_length(assumptions) > 0",
            name="ck_gap_exposure_has_assumptions",
        ),
        # Invariant 3 — a modelled value always carries its confidence.
        CheckConstraint(
            "exposure_base IS NULL OR confidence_score IS NOT NULL",
            name="ck_gap_exposure_has_confidence",
        ),
        CheckConstraint(
            "confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)",
            name="ck_gap_confidence_range",
        ),
        # Invariant 4 — terminal timestamps match terminal status.
        CheckConstraint(
            "(status = 'resolved') = (resolved_at IS NOT NULL)", name="ck_gap_resolved_at"
        ),
        CheckConstraint(
            "(status = 'dismissed') = (dismissed_at IS NOT NULL)", name="ck_gap_dismissed_at"
        ),
        CheckConstraint(
            "status <> 'resolved' OR outcome_id IS NOT NULL", name="ck_gap_resolved_has_outcome"
        ),
        # Invariant 5 — the observation window is coherent.
        CheckConstraint(
            "first_seen_at <= last_seen_at AND last_seen_at <= as_of_at",
            name="ck_gap_timeline_ordered",
        ),
        Index("ix_gaps_org_status", "organization_id", "status"),
        Index("ix_gaps_org_exposure", "organization_id", "exposure_base"),
        # Invariant 6 - the same finding is not raised twice while it is still
        # open. Partial, not total: once a gap is resolved or dismissed the same
        # condition recurring is a new gap and must be raisable again.
        #
        # This is declared here as well as in migration 0002 because the test
        # fixture builds its schema from this metadata. An index that exists only
        # in the migration is an index the tests cannot prove;
        # test_the_migration_creates_every_index_the_models_declare keeps the two
        # honest.
        Index(
            "uq_gap_dedupe_open",
            "organization_id",
            "dedupe_key",
            unique=True,
            postgresql_where=text("status NOT IN ('resolved', 'dismissed')"),
        ),
    )


# ---------------------------------------------------------------------------
# The data plane (Phase C)
# ---------------------------------------------------------------------------


class Connection(Base):
    """One configured source for one organization.

    `config` holds settings and **never secrets**. Secrets live in the secret
    manager and reach a connector through the resolver on ConnectorContext, so
    a database backup, a support export or a stray log of this row yields
    nothing usable. `ck_connection_config_has_no_secrets` is the structural
    version of that promise: a config containing a key that looks like a
    credential is refused by the database rather than by a code review.
    """

    __tablename__ = "connections"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    connector_key: Mapped[str] = mapped_column(String(64), nullable=False)
    connector_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="configured")
    is_fixture: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_successful_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expected_cadence_seconds: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_connection_org_name"),
        CheckConstraint(
            "status IN ('configured','testing','syncing','healthy','delayed',"
            "'schema_changed','failed','disabled','fixture')",
            name="ck_connection_status",
        ),
        # A fixture connection is never dressed as healthy. The connector card
        # shows real state, and this is the rule made unbreakable.
        CheckConstraint(
            "NOT (is_fixture AND status = 'healthy')",
            name="ck_connection_fixture_is_not_healthy",
        ),
        CheckConstraint(
            "NOT (config::text ~* '(password|secret|token|api[_-]?key|private[_-]?key)')",
            name="ck_connection_config_has_no_secrets",
        ),
        Index("ix_connections_org", "organization_id"),
    )


class MappingVersion(Base):
    """How a source record becomes a staging row, versioned and immutable.

    Immutable is the point. A correction is a *new* version applied forward over
    the same raw objects, never an edit of the one that produced the numbers
    somebody already acted on. Freezing an applied version needs to compare the
    old row with the new one, which a CHECK constraint cannot do, so it is a
    trigger — `mapping_versions_freeze_applied` in migration 0005. Only
    `is_active` may change afterwards, which is what makes rollback possible
    without making history editable.

    Exactly one version per (connection, resource) is active, enforced by a
    partial unique index rather than by application code — two active mappings
    means two answers to "how was this row produced".
    """

    __tablename__ = "mapping_versions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("connections.id", ondelete="CASCADE"), nullable=False
    )
    resource: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    column_map: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    required_columns: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    transforms: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    target_table: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "connection_id", "resource", "version", name="uq_mapping_connection_resource_version"
        ),
        CheckConstraint("version >= 1", name="ck_mapping_version_positive"),
        CheckConstraint(
            "jsonb_typeof(column_map) = 'object' AND column_map <> '{}'::jsonb",
            name="ck_mapping_has_columns",
        ),
        # An active version must have been applied, and vice versa. Otherwise
        # "which mapping is live" and "which mapping ran" can disagree.
        CheckConstraint("is_active = (applied_at IS NOT NULL)", name="ck_mapping_active_applied"),
        Index(
            "uq_mapping_one_active_per_resource",
            "connection_id",
            "resource",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        Index("ix_mapping_versions_org", "organization_id"),
    )


class ConnectorRun(Base):
    """The record of one extraction. Append-only, like the audit log.

    Every count here answers a question somebody asks during an incident, and
    `records_quarantined` is not nullable on purpose: a run that cannot say how
    many records it rejected is a run reporting a number nobody should trust.
    """

    __tablename__ = "connector_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("connections.id", ondelete="CASCADE"), nullable=False
    )
    connector_key: Mapped[str] = mapped_column(String(64), nullable=False)
    connector_version: Mapped[int] = mapped_column(Integer, nullable=False)
    mapping_version: Mapped[int | None] = mapped_column(Integer)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, server_default="manual")
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, server_default="running")
    records_read: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    records_written: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    records_quarantined: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    rate_limit_waits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checkpoint: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    resources: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    secrets_used: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    error: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "outcome IN ('running','succeeded','partial','failed')", name="ck_run_outcome"
        ),
        CheckConstraint(
            "trigger IN ('manual','schedule','webhook','backfill')", name="ck_run_trigger"
        ),
        CheckConstraint(
            "records_read >= 0 AND records_written >= 0 AND records_quarantined >= 0",
            name="ck_run_counts_non_negative",
        ),
        # A finished run has an end time; a running one does not. Without this,
        # "how long did it take" has no reliable answer.
        CheckConstraint("(outcome = 'running') = (finished_at IS NULL)", name="ck_run_finished_at"),
        # A failure has to say why. A failed run with no error is an incident
        # with no starting point.
        CheckConstraint("outcome <> 'failed' OR error IS NOT NULL", name="ck_run_failed_has_error"),
        Index("ix_runs_org_started", "organization_id", "started_at"),
        Index("ix_runs_connection", "connection_id", "started_at"),
    )


class QuarantinedRecord(Base):
    """A rejected record, kept with its reason and its mapping version.

    Kept rather than dropped, because silent rejection is prohibited, and
    because a mapping fix is applied forward — which needs the rejected records
    to still exist to be re-run against.
    """

    __tablename__ = "quarantined_records"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("connector_runs.id", ondelete="CASCADE"), nullable=False
    )
    connector_key: Mapped[str] = mapped_column(String(64), nullable=False)
    resource: Mapped[str] = mapped_column(String(64), nullable=False)
    source_record_id: Mapped[str] = mapped_column(String(400), nullable=False)
    raw_ref: Mapped[str] = mapped_column(Text, nullable=False)
    mapping_version: Mapped[int] = mapped_column(Integer, nullable=False)
    reasons: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quarantined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # A quarantine entry with no reason is a rejection nobody can act on.
        CheckConstraint("jsonb_array_length(reasons) > 0", name="ck_quarantine_has_reason"),
        # And it must still point at the bytes, or it cannot be investigated.
        CheckConstraint("raw_ref <> ''", name="ck_quarantine_has_raw_ref"),
        Index("ix_quarantine_org_run", "organization_id", "run_id"),
        Index("ix_quarantine_org_time", "organization_id", "quarantined_at"),
    )


class WebhookDelivery(Base):
    """Every delivery seen, once. This is release gate 8, as a table.

    The unique constraint is the whole mechanism. Checking for an existing row
    and then inserting is a race two workers lose together: both see "not
    seen", both insert, and the duplicate the check existed to prevent happens
    anyway. `INSERT ... ON CONFLICT DO NOTHING` and the constraint make the
    decision atomic.

    Keyed per organization, because sources number their deliveries from 1 for
    everybody and two tenants will collide on day one.
    """

    __tablename__ = "webhook_deliveries"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    connector_key: Mapped[str] = mapped_column(String(64), nullable=False)
    delivery_id: Mapped[str] = mapped_column(String(200), nullable=False)
    raw_ref: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "connector_key",
            "delivery_id",
            name="uq_webhook_delivery_once",
        ),
        Index("ix_webhook_deliveries_org_time", "organization_id", "received_at"),
    )
