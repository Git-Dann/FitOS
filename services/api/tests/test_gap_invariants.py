"""The Gap invariants, enforced by the database.

Each test here tries to write a gap that violates a non-negotiable rule and
asserts PostgreSQL refuses. That is the point of putting them in CHECK
constraints: a rule enforced only in a service layer can be bypassed by a data
fix, a migration script, or an endpoint written next year.

The rules come from CLAUDE.md and docs/gap-model.md §1:

  no gap without a metric version, detector version, evidence and an as-of time
  no modelled money without low, base, high, assumptions and confidence
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from conftest import requires_db
from fitos_api.db import organization_scope
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

pytestmark = requires_db

NOW = datetime.now(UTC)


def gap_values(org: uuid.UUID, **overrides: Any) -> dict[str, Any]:
    """A minimal valid gap. Each test breaks exactly one thing."""
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "organization_id": org,
        "pack_key": "retail_omnichannel",
        "gap_type": "stock_truth_mismatch",
        "title": "Size 32 Charcoal not found on 7 checks",
        "summary": "System stock shows units available; staff checks disagree.",
        "scope_type": "product_variant",
        "scope_id": "NS-014/CH-PL-041",
        "metric_definition_id": uuid.uuid4(),
        "metric_version": 2,
        "observed_value": 7,
        "expected_value": 1,
        "absolute_delta": 6,
        "percentage_delta": 600,
        "unit": "count",
        "currency": "GBP",
        "exposure_low": 82000,
        "exposure_base": 145000,
        "exposure_high": 240000,
        "confidence_score": 0.58,
        "confidence_band": "medium",
        "severity": "critical",
        "status": "detected",
        "first_seen_at": NOW - timedelta(days=6),
        "last_seen_at": NOW - timedelta(hours=2),
        "as_of_at": NOW,
        "rule_id": uuid.uuid4(),
        "rule_version": 3,
        "detector_run_id": uuid.uuid4(),
        "assumptions": '[{"key":"recovery_probability","value":0.35}]',
        "evidence_refs": '[{"canonical_entity":"fact_stock_check","canonical_record_id":"1"}]',
        "recommended_actions": "[]",
        "reason_codes": "[]",
        "dedupe_key": f"dk-{uuid.uuid4().hex[:16]}",
    }
    values.update(overrides)
    return values


INSERT = text(
    """
    INSERT INTO gaps (
      id, organization_id, pack_key, gap_type, title, summary, scope_type, scope_id,
      metric_definition_id, metric_version, observed_value, expected_value,
      absolute_delta, percentage_delta, unit, currency,
      exposure_low, exposure_base, exposure_high,
      confidence_score, confidence_band, severity, status,
      first_seen_at, last_seen_at, as_of_at,
      rule_id, rule_version, detector_run_id,
      assumptions, evidence_refs, recommended_actions, reason_codes, dedupe_key,
      resolved_at, dismissed_at, outcome_id
    ) VALUES (
      :id, :organization_id, :pack_key, :gap_type, :title, :summary, :scope_type, :scope_id,
      :metric_definition_id, :metric_version, :observed_value, :expected_value,
      :absolute_delta, :percentage_delta, :unit, :currency,
      :exposure_low, :exposure_base, :exposure_high,
      :confidence_score, :confidence_band, :severity, :status,
      :first_seen_at, :last_seen_at, :as_of_at,
      :rule_id, :rule_version, :detector_run_id,
      cast(:assumptions as jsonb), cast(:evidence_refs as jsonb),
      cast(:recommended_actions as jsonb), cast(:reason_codes as jsonb), :dedupe_key,
      :resolved_at, :dismissed_at, :outcome_id
    )
    """
)


def insert_gap(session: Session, org: uuid.UUID, **overrides: Any) -> None:
    values = gap_values(org, **overrides)
    values.setdefault("resolved_at", None)
    values.setdefault("dismissed_at", None)
    values.setdefault("outcome_id", None)
    session.execute(INSERT, values)
    session.flush()


def assert_refused(session: Session, org: uuid.UUID, constraint: str, **overrides: Any) -> None:
    with pytest.raises(IntegrityError) as exc:
        insert_gap(session, org, **overrides)
    assert constraint in str(exc.value), f"expected {constraint}, got: {exc.value}"
    session.rollback()


def test_a_valid_gap_is_accepted(
    app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """The baseline. Without it, every refusal below could be a false positive."""
    org_a, _ = two_orgs
    with organization_scope(app_session, org_a):
        insert_gap(app_session, org_a)
        count = app_session.execute(text("SELECT count(*) FROM gaps")).scalar()
    assert count == 1


class TestNoGapWithoutEvidence:
    """CLAUDE.md: no gap without a metric version, detector version, evidence
    and an as-of time."""

    def test_empty_evidence_is_refused(
        self, app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        org_a, _ = two_orgs
        with organization_scope(app_session, org_a):
            assert_refused(app_session, org_a, "ck_gap_has_evidence", evidence_refs="[]")

    def test_a_null_metric_version_is_refused(
        self, app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        org_a, _ = two_orgs
        with organization_scope(app_session, org_a):
            with pytest.raises(IntegrityError, match="metric_version"):
                insert_gap(app_session, org_a, metric_version=None)
            app_session.rollback()

    def test_a_null_rule_version_is_refused(
        self, app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        org_a, _ = two_orgs
        with organization_scope(app_session, org_a):
            with pytest.raises(IntegrityError, match="rule_version"):
                insert_gap(app_session, org_a, rule_version=None)
            app_session.rollback()

    def test_a_null_as_of_time_is_refused(
        self, app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        org_a, _ = two_orgs
        with organization_scope(app_session, org_a):
            with pytest.raises(IntegrityError, match="as_of_at"):
                insert_gap(app_session, org_a, as_of_at=None)
            app_session.rollback()


class TestNoModelledMoneyWithoutARange:
    """CLAUDE.md: no modelled money without low, base, high, assumptions and
    confidence. A point estimate is the specific thing this forbids."""

    def test_a_bare_point_estimate_is_refused(
        self, app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        org_a, _ = two_orgs
        with organization_scope(app_session, org_a):
            assert_refused(
                app_session,
                org_a,
                "ck_gap_exposure_all_or_none",
                exposure_low=None,
                exposure_high=None,
            )

    def test_an_out_of_order_range_is_refused(
        self, app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        org_a, _ = two_orgs
        with organization_scope(app_session, org_a):
            assert_refused(
                app_session, org_a, "ck_gap_exposure_ordered", exposure_low=999999, exposure_base=1
            )

    def test_money_without_a_currency_is_refused(
        self, app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        org_a, _ = two_orgs
        with organization_scope(app_session, org_a):
            assert_refused(app_session, org_a, "ck_gap_exposure_has_currency", currency=None)

    def test_money_without_assumptions_is_refused(
        self, app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """A range with no stated assumptions is a number with a false air of
        rigour."""
        org_a, _ = two_orgs
        with organization_scope(app_session, org_a):
            assert_refused(app_session, org_a, "ck_gap_exposure_has_assumptions", assumptions="[]")

    def test_money_without_confidence_is_refused(
        self, app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        org_a, _ = two_orgs
        with organization_scope(app_session, org_a):
            assert_refused(
                app_session, org_a, "ck_gap_exposure_has_confidence", confidence_score=None
            )

    def test_confidence_outside_zero_to_one_is_refused(
        self, app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        org_a, _ = two_orgs
        with organization_scope(app_session, org_a):
            assert_refused(app_session, org_a, "ck_gap_confidence_range", confidence_score=1.5)

    def test_a_gap_with_no_exposure_at_all_is_fine(
        self, app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """Data-quality gaps carry no exposure — there is nothing to model.

        The rule constrains modelled values; a null is not one.
        """
        org_a, _ = two_orgs
        with organization_scope(app_session, org_a):
            insert_gap(
                app_session,
                org_a,
                gap_type="source_freshness_stall",
                exposure_low=None,
                exposure_base=None,
                exposure_high=None,
                currency=None,
                confidence_score=0.95,
                confidence_band="high",
                assumptions="[]",
            )
            count = app_session.execute(text("SELECT count(*) FROM gaps")).scalar()
        assert count == 1


class TestLifecycleConsistency:
    def test_resolved_without_a_timestamp_is_refused(
        self, app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        org_a, _ = two_orgs
        with organization_scope(app_session, org_a):
            assert_refused(
                app_session,
                org_a,
                "ck_gap_resolved_at",
                status="resolved",
                resolved_at=None,
                outcome_id=uuid.uuid4(),
            )

    def test_resolved_without_an_outcome_is_refused(
        self, app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """Resolution means something was measured, even if the measurement was
        'no measurable change'."""
        org_a, _ = two_orgs
        with organization_scope(app_session, org_a):
            assert_refused(
                app_session,
                org_a,
                "ck_gap_resolved_has_outcome",
                status="resolved",
                resolved_at=NOW,
                outcome_id=None,
            )

    def test_a_resolved_timestamp_on_an_open_gap_is_refused(
        self, app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        org_a, _ = two_orgs
        with organization_scope(app_session, org_a):
            assert_refused(app_session, org_a, "ck_gap_resolved_at", resolved_at=NOW)

    def test_an_unknown_status_is_refused(
        self, app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        org_a, _ = two_orgs
        with organization_scope(app_session, org_a):
            assert_refused(app_session, org_a, "ck_gap_status", status="probably_fine")

    def test_a_timeline_running_backwards_is_refused(
        self, app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        org_a, _ = two_orgs
        with organization_scope(app_session, org_a):
            assert_refused(
                app_session,
                org_a,
                "ck_gap_timeline_ordered",
                first_seen_at=NOW,
                last_seen_at=NOW - timedelta(days=1),
            )


class TestDedupe:
    """One evolving gap per problem, not one row per detector run."""

    def test_a_second_open_gap_with_the_same_key_is_refused(
        self, app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        org_a, _ = two_orgs
        key = f"dk-{uuid.uuid4().hex[:16]}"
        with organization_scope(app_session, org_a):
            insert_gap(app_session, org_a, dedupe_key=key)
            with pytest.raises(IntegrityError, match="uq_gap_dedupe_open"):
                insert_gap(app_session, org_a, dedupe_key=key)
            app_session.rollback()

    def test_the_same_key_is_allowed_once_the_first_is_resolved(
        self, app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """A recurrence months later is a new gap, not a blocked write.

        This is why the unique index is partial.
        """
        org_a, _ = two_orgs
        key = f"dk-{uuid.uuid4().hex[:16]}"
        with organization_scope(app_session, org_a):
            insert_gap(
                app_session,
                org_a,
                dedupe_key=key,
                status="resolved",
                resolved_at=NOW,
                outcome_id=uuid.uuid4(),
            )
            insert_gap(app_session, org_a, dedupe_key=key)
            count = app_session.execute(text("SELECT count(*) FROM gaps")).scalar()
        assert count == 2

    def test_the_same_key_in_another_organization_is_allowed(
        self, app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """Dedupe is per tenant. Two retailers can have the same problem."""
        org_a, org_b = two_orgs
        key = f"dk-{uuid.uuid4().hex[:16]}"
        with organization_scope(app_session, org_a):
            insert_gap(app_session, org_a, dedupe_key=key)
            app_session.commit()
        with organization_scope(app_session, org_b):
            insert_gap(app_session, org_b, dedupe_key=key)
            app_session.commit()
        with organization_scope(app_session, org_b):
            visible = app_session.execute(text("SELECT count(*) FROM gaps")).scalar()
        assert visible == 1, "org B should see only its own gap"


class TestGapsAreTenantScoped:
    def test_a_gap_is_invisible_to_another_organization(
        self, app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        org_a, org_b = two_orgs
        with organization_scope(app_session, org_a):
            insert_gap(app_session, org_a)
            app_session.commit()
        with organization_scope(app_session, org_b):
            rows = app_session.execute(text("SELECT id FROM gaps")).scalars().all()
        assert rows == []

    def test_the_app_role_cannot_delete_a_gap(
        self, app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        """A gap is dismissed, never deleted.

        Deleting one removes the record that it was ever raised — the same
        repudiation problem the audit table has.
        """
        from sqlalchemy.exc import ProgrammingError

        org_a, _ = two_orgs
        with organization_scope(app_session, org_a):
            insert_gap(app_session, org_a)
            with pytest.raises(ProgrammingError, match="permission denied"):
                app_session.execute(text("DELETE FROM gaps"))
            app_session.rollback()
