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
