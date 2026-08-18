"""Persisting detector output.

The one place a `GapCandidate` becomes a `Gap` row, and the one place a
`DetectorRun` record is written. Both matter for the same reason: a second
write path is a second set of invariants, and the second set is always the one
that is slightly wrong.

Three rules the writer enforces that neither the detector nor the database can:

**An update leaves human state alone.** `first_seen_at`, `status` and `owner_id`
belong to whoever has been working the gap. A detector re-firing updates the
measurement and the timeline and touches nothing else — gap-model.md §6. A
detector that could reset `status` would undo somebody's triage every night.

**A create and an update produce the same measurement.** The two paths set the
same columns from the same candidate, so a gap that has been seen twice is not
subtly different from one seen once.

**The run record is written even when nothing was found, and even when the
detector failed.** A run that produced no gaps because it errored looks exactly
like a clean one unless the record says otherwise.

The writer is deliberately not a route. Detectors run in Temporal activities
against the control plane directly (docs/architecture.md §3, "Detect"), and the
worker imports this module. The one-inbound-door rule is about the browser: a
worker posting its own output back through HTTP would buy nothing and lose the
transaction that keeps a gap and its run record consistent.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fitos_api.models import DetectorRun, Gap


def _percentage_delta(observed: float, expected: float) -> float | None:
    """Null against a zero baseline, never infinity and never a cap.

    A percentage against zero has no meaning; presenting one as ∞% or 100%
    invents a figure and both look like data.
    """
    if expected == 0:
        return None
    return (observed - expected) / expected


def open_gaps_for(session: Session, *, pack_key: str | None = None) -> list[dict[str, Any]]:
    """The non-terminal gaps the pipeline needs to dedupe and suppress against.

    No organization predicate: RLS supplies it, and the cross-tenant tests
    assert that is safe rather than assuming it.
    """
    query = select(Gap).where(Gap.status.notin_(("resolved", "dismissed")))
    if pack_key is not None:
        query = query.where(Gap.pack_key == pack_key)
    return [
        {
            "gap_id": gap.id,
            "dedupe_key": gap.dedupe_key,
            "gap_type": gap.gap_type,
            "scope_type": gap.scope_type,
            "scope_id": gap.scope_id,
            "status": gap.status,
        }
        for gap in session.execute(query).scalars().all()
    ]


def _measurement_fields(candidate: Any, *, detector_run_id: uuid.UUID) -> dict[str, Any]:
    """Everything a detector re-firing is allowed to change.

    Named once and used by both the create and the update path, so the two
    cannot drift into setting different things.
    """
    exposure = candidate.exposure
    observed = float(candidate.observed_value)
    expected = float(candidate.expected_value)
    return {
        "title": candidate.title,
        "summary": candidate.summary,
        "observed_value": observed,
        "expected_value": expected,
        "absolute_delta": abs(observed - expected),
        "percentage_delta": _percentage_delta(observed, expected),
        "unit": candidate.unit.value,
        "currency": exposure.currency if exposure else None,
        "exposure_low": exposure.low_minor if exposure else None,
        "exposure_base": exposure.base_minor if exposure else None,
        "exposure_high": exposure.high_minor if exposure else None,
        "assumptions": list(exposure.assumptions) if exposure else [],
        "confidence_score": candidate.confidence.score,
        "confidence_band": candidate.confidence.band.value,
        "severity": candidate.severity.value,
        "last_seen_at": candidate.window.end,
        "as_of_at": candidate.window.as_of,
        "data_freshness_seconds": candidate.data_freshness_seconds,
        "evidence_refs": [ref.model_dump(mode="json") for ref in candidate.evidence],
        "recommended_actions": [dict(a) for a in candidate.recommended_actions],
        "reason_codes": list(candidate.reason_codes),
        "detector_run_id": detector_run_id,
    }


def create_gap(
    session: Session,
    candidate: Any,
    *,
    organization_id: uuid.UUID,
    dedupe_key: str,
    rule_id: uuid.UUID,
    rule_version: int,
    metric_definition_id: uuid.UUID,
    detector_run_id: uuid.UUID,
) -> Gap:
    gap = Gap(
        organization_id=organization_id,
        pack_key=candidate.pack_key,
        gap_type=candidate.gap_type,
        scope_type=candidate.scope_type.value,
        scope_id=candidate.scope_id,
        metric_definition_id=metric_definition_id,
        metric_version=candidate.metric_version,
        status="detected",
        first_seen_at=candidate.window.end,
        rule_id=rule_id,
        rule_version=rule_version,
        dedupe_key=dedupe_key,
        **_measurement_fields(candidate, detector_run_id=detector_run_id),
    )
    session.add(gap)
    session.flush()
    return gap


def update_gap(
    session: Session,
    gap: Gap,
    candidate: Any,
    *,
    rule_version: int,
    detector_run_id: uuid.UUID,
) -> Gap:
    """Refresh the measurement and the timeline. Nothing else.

    `first_seen_at`, `status`, `owner_id` and `lifecycle_version` are untouched:
    they are human state, and a detector that reset them would undo somebody's
    triage every night. `lifecycle_version` in particular must not move here, or
    a detector run would invalidate every open editor's optimistic-concurrency
    token for reasons that have nothing to do with a human edit.
    """
    for field, value in _measurement_fields(candidate, detector_run_id=detector_run_id).items():
        setattr(gap, field, value)
    gap.rule_version = rule_version
    session.flush()
    return gap


def record_detector_run(
    session: Session,
    *,
    organization_id: uuid.UUID,
    detector_key: str,
    pack_key: str,
    rule_id: uuid.UUID,
    rule_version: int,
    config_fingerprint: str,
    window_start: datetime,
    window_end: datetime,
    started_at: datetime,
    finished_at: datetime,
    readings_considered: int,
    insufficient_readings: int,
    candidates_produced: int,
    candidates_suppressed: int,
    gaps_created: int,
    gaps_updated: int,
    correlations_linked: int,
    query_hashes: list[str],
    dedupe_decisions: list[dict[str, Any]],
    thresholds: dict[str, Any],
    errors: list[str],
    skipped_reason: str | None = None,
    run_id: uuid.UUID | None = None,
) -> DetectorRun:
    """Written on every run, including one that found nothing or failed.

    Duration comes from the caller rather than being measured here: a detector
    body is pure and cannot read a clock, so the activity that invoked it is the
    only honest place to time it.
    """
    run = DetectorRun(
        id=run_id or uuid.uuid4(),
        organization_id=organization_id,
        detector_key=detector_key,
        pack_key=pack_key,
        rule_id=rule_id,
        rule_version=rule_version,
        config_fingerprint=config_fingerprint,
        window_start=window_start,
        window_end=window_end,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=max(0, int((finished_at - started_at).total_seconds() * 1000)),
        readings_considered=readings_considered,
        insufficient_readings=insufficient_readings,
        candidates_produced=candidates_produced,
        candidates_suppressed=candidates_suppressed,
        gaps_created=gaps_created,
        gaps_updated=gaps_updated,
        correlations_linked=correlations_linked,
        query_hashes=query_hashes,
        dedupe_decisions=dedupe_decisions,
        thresholds=thresholds,
        errors=errors,
        skipped_reason=skipped_reason,
    )
    session.add(run)
    session.flush()
    return run
