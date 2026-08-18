"""The Stock Truth Gap end to end.

Phase D's outcome: *the Stock Truth Gap exists end to end, from seeded records
to an assigned action and a recorded outcome, provable through the API.*

This is that proof, run against a real PostgreSQL rather than a fixture double.
Six days of detector runs over deteriorating stock readings produce **one**
evolving gap — the dedupe release gate — which is then assigned, actioned and
resolved with an outcome through the HTTP API, with the audit rows and the
detector run records to show for it.

Each stage asserts something a stage-by-stage unit test cannot: that the
detector's output is actually writable, that the writer's rows are actually
readable through the API, and that the API's transitions actually satisfy the
database's invariants. Every one of those seams has been a real bug in this
build.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from conftest import auth, requires_db
from fastapi.testclient import TestClient
from fitos_api.db import organization_scope
from fitos_api.gaps.writer import (
    create_gap,
    open_gaps_for,
    record_detector_run,
    update_gap,
)
from fitos_worker.detectors.base import DetectorContext, MetricReading, ObservationWindow
from fitos_worker.detectors.pipeline import DedupeDecision, OpenGap, reconcile
from fitos_worker.detectors.source_mismatch import SourceMismatchConfig, SourceMismatchDetector
from sqlalchemy import text
from sqlalchemy.orm import Session

pytestmark = requires_db

RULE_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
METRIC_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")

# Six days of the same location drifting further from its records. The values
# rise so the gap has a story; the dedupe key must not notice, because the
# problem is the same problem.
DAILY_RATES = ["0.11", "0.14", "0.19", "0.23", "0.28", "0.34"]


def _reading(day: int, rate: str) -> MetricReading:
    return MetricReading(
        metric_key="stock_discrepancy_rate",
        metric_version=1,
        query_hash=f"stock-truth-day-{day}",
        dimensions={"location_id": "store-oxford-street"},
        value=Decimal(rate),
        denominator=120,
        captured_at=datetime(2026, 8, day + 1, tzinfo=UTC),
        source_max_timestamp=datetime(2026, 8, day + 1, tzinfo=UTC) - timedelta(hours=2),
    )


def _run_detector_for_day(session: Session, organization_id: uuid.UUID, day: int) -> dict[str, Any]:
    """One day's detector run, from reading to persisted gap and run record."""
    window = ObservationWindow(
        start=datetime(2026, 8, day, tzinfo=UTC), end=datetime(2026, 8, day + 1, tzinfo=UTC)
    )
    context = DetectorContext(organization_id=organization_id, window=window, as_of=window.end)
    detector = SourceMismatchDetector(
        SourceMismatchConfig(rule_id=RULE_ID, version=1, pack_key="retail_omnichannel")
    )

    started = datetime.now(UTC)
    result = detector.run([_reading(day, DAILY_RATES[day - 1])], context)

    existing = [OpenGap(**row) for row in open_gaps_for(session)]
    reconciled = reconcile([result], organization_id=organization_id, open_gaps=existing)

    run_id = uuid.uuid4()
    created = updated = 0
    for outcome in reconciled.outcomes:
        if outcome.decision is DedupeDecision.CREATE:
            create_gap(
                session,
                outcome.candidate,
                organization_id=organization_id,
                dedupe_key=outcome.dedupe_key,
                rule_id=RULE_ID,
                rule_version=1,
                metric_definition_id=METRIC_ID,
                detector_run_id=run_id,
            )
            created += 1
        else:
            gap = next(
                g
                for g in session.query(__import__("fitos_api.models", fromlist=["Gap"]).Gap).all()
                if g.dedupe_key == outcome.dedupe_key
            )
            update_gap(session, gap, outcome.candidate, rule_version=1, detector_run_id=run_id)
            updated += 1

    record_detector_run(
        session,
        run_id=run_id,
        organization_id=organization_id,
        detector_key=detector.key,
        pack_key="retail_omnichannel",
        rule_id=RULE_ID,
        rule_version=1,
        config_fingerprint=detector.config.fingerprint(),
        window_start=window.start,
        window_end=window.end,
        started_at=started,
        finished_at=datetime.now(UTC),
        readings_considered=result.readings_considered,
        insufficient_readings=result.insufficient_readings,
        candidates_produced=reconciled.candidates_produced,
        candidates_suppressed=reconciled.candidates_suppressed,
        gaps_created=created,
        gaps_updated=updated,
        correlations_linked=reconciled.correlations_linked,
        query_hashes=result.query_hash_list(),
        dedupe_decisions=reconciled.dedupe_decisions(),
        thresholds=detector.config.model_dump(mode="json"),
        errors=list(result.errors),
    )
    session.commit()
    return {"created": created, "updated": updated}


@pytest.fixture
def slice_org(owner_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]) -> dict[str, Any]:
    org_a, org_b = two_orgs
    member = owner_session.execute(
        text("SELECT id, user_id FROM memberships WHERE organization_id = :o"), {"o": org_a}
    ).one()
    return {"org": org_a, "other_org": org_b, "membership": member[0], "user": member[1]}


@pytest.fixture
def six_days(app_engine: Any, slice_org: dict[str, Any]) -> dict[str, Any]:
    """Run the detector once per day for six days, as a scheduled workflow would."""
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=app_engine, expire_on_commit=False)
    totals = {"created": 0, "updated": 0}
    for day in range(1, 7):
        # A fresh session and a fresh scope per day, exactly as a scheduled
        # workflow gets. Reusing one transaction across six days would hide a
        # scoping bug that only appears once the connection is recycled.
        session = factory()
        with organization_scope(session, slice_org["org"]):
            result = _run_detector_for_day(session, slice_org["org"], day)
        totals["created"] += result["created"]
        totals["updated"] += result["updated"]
        session.close()
    return {**slice_org, **totals}


# ---------------------------------------------------------------------------
# Stage 1 — six days of readings produce one evolving gap
# ---------------------------------------------------------------------------


def test_six_days_of_detection_produce_one_gap(
    six_days: dict[str, Any], owner_session: Session
) -> None:
    """RELEASE GATE, against the real database rather than in memory.

    The in-memory pipeline test proves the dedupe key is stable. This proves the
    partial unique index, the writer and the reconciler agree with it — the
    seam where "one gap" quietly becomes six.
    """
    rows = owner_session.execute(
        text(
            "SELECT id, status, observed_value, first_seen_at, last_seen_at FROM gaps "
            "WHERE organization_id = :o"
        ),
        {"o": six_days["org"]},
    ).all()

    assert len(rows) == 1, f"six days produced {len(rows)} gaps"
    assert six_days["created"] == 1
    assert six_days["updated"] == 5


def test_the_gap_carries_the_latest_measurement_and_the_original_first_seen(
    six_days: dict[str, Any], owner_session: Session
) -> None:
    """The timeline is the point: it started on day one and is worse now."""
    row = owner_session.execute(
        text(
            "SELECT observed_value, first_seen_at, last_seen_at, severity FROM gaps "
            "WHERE organization_id = :o"
        ),
        {"o": six_days["org"]},
    ).one()
    observed, first_seen, last_seen, severity = row

    assert float(observed) == pytest.approx(0.34), "the gap shows the newest reading"
    assert first_seen == datetime(2026, 8, 2, tzinfo=UTC), "first_seen_at is day one"
    assert last_seen == datetime(2026, 8, 7, tzinfo=UTC), "last_seen_at is day six"
    assert severity == "critical", "0.34 is past the critical threshold"


def test_every_day_wrote_a_detector_run_record(
    six_days: dict[str, Any], owner_session: Session
) -> None:
    """Including the five that created nothing. A run that found nothing new is
    still a run somebody may need to account for."""
    rows = owner_session.execute(
        text(
            "SELECT gaps_created, gaps_updated, readings_considered, duration_ms, "
            "query_hashes, thresholds FROM detector_runs WHERE organization_id = :o "
            "ORDER BY window_start"
        ),
        {"o": six_days["org"]},
    ).all()

    assert len(rows) == 6
    assert [r[0] for r in rows] == [1, 0, 0, 0, 0, 0]
    assert [r[1] for r in rows] == [0, 1, 1, 1, 1, 1]
    assert all(r[2] == 1 for r in rows)
    assert all(r[3] >= 0 for r in rows)
    assert rows[0][4] == ["stock-truth-day-1"], "the run records the query it ran"
    assert rows[0][5]["threshold_rate"] == "0.05", "and the thresholds it ran with"


def test_the_detector_run_records_are_tenant_scoped(
    six_days: dict[str, Any], owner_session: Session
) -> None:
    count = owner_session.execute(
        text("SELECT count(*) FROM detector_runs WHERE organization_id = :o"),
        {"o": six_days["other_org"]},
    ).scalar()
    assert count == 0


# ---------------------------------------------------------------------------
# Stage 2 — the gap is complete enough to act on
# ---------------------------------------------------------------------------


def test_the_gap_satisfies_the_aggregate_invariants(
    six_days: dict[str, Any], owner_session: Session
) -> None:
    """Not asserted by reading the constraints: the row exists, so the database
    accepted it. This states what that acceptance means."""
    row = owner_session.execute(
        text(
            "SELECT metric_definition_id, metric_version, rule_version, as_of_at, "
            "jsonb_array_length(evidence_refs), exposure_low, exposure_base, exposure_high, "
            "currency, jsonb_array_length(assumptions), confidence_score "
            "FROM gaps WHERE organization_id = :o"
        ),
        {"o": six_days["org"]},
    ).one()

    (
        metric_id,
        metric_version,
        rule_version,
        as_of,
        evidence,
        low,
        base,
        high,
        ccy,
        assumptions,
        confidence,
    ) = row

    assert metric_id and metric_version and rule_version and as_of
    assert evidence >= 1, "no gap without evidence"
    assert low is not None and base is not None and high is not None
    assert low <= base <= high
    assert ccy == "GBP", "no modelled money without a currency"
    assert assumptions >= 1, "no modelled money without assumptions"
    assert confidence is not None, "no modelled money without confidence"


def test_the_evidence_resolves_back_to_the_query_that_produced_it(
    six_days: dict[str, Any], owner_session: Session
) -> None:
    """From a gap a user must reach the metric definition, the version and the
    exact compiled query — without guessing how a number was produced."""
    refs = owner_session.execute(
        text("SELECT evidence_refs FROM gaps WHERE organization_id = :o"),
        {"o": six_days["org"]},
    ).scalar()

    assert refs, "a gap with no evidence should not have been writable at all"
    ref = refs[0]
    assert ref["metric_key"] == "stock_discrepancy_rate"
    assert ref["metric_version"] == 1
    assert ref["query_hash"] == "stock-truth-day-6", "the newest run's query"
    assert ref["observation_window"]["start"].startswith("2026-08-06")
    assert ref["query_parameters"] == {"location_id": "store-oxford-street"}


def test_the_gap_states_no_cause(six_days: dict[str, Any], owner_session: Session) -> None:
    title, summary = owner_session.execute(
        text("SELECT title, summary FROM gaps WHERE organization_id = :o"),
        {"o": six_days["org"]},
    ).one()
    text_content = f"{title} {summary}".lower()
    for word in ("shrinkage", "theft", "caused", "because", "due to"):
        assert word not in text_content


# ---------------------------------------------------------------------------
# Stage 3 — assign, action and resolve through the API
# ---------------------------------------------------------------------------


def test_the_gap_can_be_worked_to_resolution_through_the_api(
    client: TestClient, keypair: Any, six_days: dict[str, Any], owner_session: Session
) -> None:
    """PHASE D OUTCOME.

    Seeded readings to an assigned action and a recorded outcome, entirely
    through the HTTP API. Every step here goes through the same routes the
    product will.
    """
    private, _ = keypair
    headers = auth(private, six_days["user"], six_days["org"])

    listed = client.get("/v1/gaps", headers=headers)
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 1
    gap_id = listed.json()[0]["id"]
    assert listed.json()[0]["gap_type"] == "stock_truth_mismatch"

    assigned = client.post(
        f"/v1/gaps/{gap_id}/assign",
        json={"owner_id": str(six_days["membership"]), "expected_version": 1},
        headers=headers,
    )
    assert assigned.status_code == 200, assigned.text
    version = assigned.json()["lifecycle_version"]

    for target in ("triaged", "investigating"):
        moved = client.post(
            f"/v1/gaps/{gap_id}/transition",
            json={"to_status": target, "expected_version": version},
            headers=headers,
        )
        assert moved.status_code == 200, moved.text
        version = moved.json()["lifecycle_version"]

    action = client.post(
        f"/v1/gaps/{gap_id}/actions",
        json={
            "title": "Recount the affected variants",
            "playbook_id": "retail.stock_truth.recount",
            "assignee_id": str(six_days["membership"]),
        },
        headers=headers,
    )
    assert action.status_code == 201, action.text

    for target in ("actioned", "validating"):
        moved = client.post(
            f"/v1/gaps/{gap_id}/transition",
            json={"to_status": target, "expected_version": version},
            headers=headers,
        )
        assert moved.status_code == 200, moved.text
        version = moved.json()["lifecycle_version"]

    outcome = client.post(
        f"/v1/gaps/{gap_id}/outcomes",
        json={
            "action_id": action.json()["id"],
            "measurement_window_start": "2026-08-08T00:00:00Z",
            "measurement_window_end": "2026-08-15T00:00:00Z",
            "metric_definition_id": str(METRIC_ID),
            "metric_version": 1,
            "value_before": 0.34,
            "value_after": 0.06,
            # pre_post, not controlled_test: nothing here establishes that the
            # recount caused the improvement, and only a controlled_test outcome
            # may use causal language.
            "method": "pre_post",
            "notes": "Discrepancy rate fell after the recount and record correction.",
        },
        headers=headers,
    )
    assert outcome.status_code == 201, outcome.text
    assert outcome.json()["delta"] == pytest.approx(-0.28)

    resolved = client.post(
        f"/v1/gaps/{gap_id}/transition",
        json={
            "to_status": "resolved",
            "expected_version": version,
            "outcome_id": outcome.json()["id"],
        },
        headers=headers,
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["resolved_at"] is not None
    assert resolved.json()["outcome_id"] == outcome.json()["id"]

    actions = owner_session.execute(
        text("SELECT count(*) FROM gap_actions WHERE gap_id = :g"), {"g": gap_id}
    ).scalar()
    outcomes = owner_session.execute(
        text("SELECT count(*) FROM gap_outcomes WHERE gap_id = :g"), {"g": gap_id}
    ).scalar()
    audit = (
        owner_session.execute(
            text("SELECT action FROM audit_events WHERE object_id = :g ORDER BY occurred_at, id"),
            {"g": gap_id},
        )
        .scalars()
        .all()
    )

    assert actions == 1
    assert outcomes == 1
    assert audit == [
        "gap.assigned",
        "gap.triaged",
        "gap.investigating",
        "gap.actioned",
        "gap.validating",
        "gap.resolved",
    ], "every transition left a record"


def test_a_resolved_gap_lets_the_same_condition_be_raised_again(
    client: TestClient, keypair: Any, six_days: dict[str, Any], app_engine: Any
) -> None:
    """The partial unique index is partial for this reason.

    Once somebody resolves a gap, the same condition recurring is new work. A
    total unique index would silently refuse the new gap, and the recurrence
    would be invisible.
    """
    from sqlalchemy.orm import sessionmaker

    private, _ = keypair
    headers = auth(private, six_days["user"], six_days["org"])
    gap_id = client.get("/v1/gaps", headers=headers).json()[0]["id"]

    client.post(
        f"/v1/gaps/{gap_id}/transition",
        json={
            "to_status": "dismissed",
            "expected_version": 1,
            "reason_code": "already_fixed",
            "note": "Corrected during the weekly count.",
        },
        headers=headers,
    )

    factory = sessionmaker(bind=app_engine, expire_on_commit=False)
    session = factory()
    with organization_scope(session, six_days["org"]):
        result = _run_detector_for_day(session, six_days["org"], 6)
    session.close()

    assert result["created"] == 1, "a recurrence after a dismissal is a new gap"
    assert len(client.get("/v1/gaps", headers=headers).json()) == 2


# ---------------------------------------------------------------------------
# The writer's own arithmetic
# ---------------------------------------------------------------------------


def test_percentage_delta_is_null_against_a_zero_baseline() -> None:
    """The writer re-derives this from floats, so it needs its own test.

    `GapCandidate.percentage_delta` has the same rule and its own test, and the
    two are separate implementations: the candidate works in Decimal and the
    row stores a float. A mutation that made the writer return 0.0 here passed
    the whole slice, because no reading in it has a zero expected value.

    Null, not zero and not infinity. A zero percentage delta against a zero
    baseline reads as "no change" when the truth is "the question does not
    apply", and both look like data.
    """
    from fitos_api.gaps.writer import _percentage_delta

    assert _percentage_delta(0.5, 0.0) is None
    assert _percentage_delta(0.0, 0.0) is None


def test_percentage_delta_keeps_its_sign() -> None:
    """Direction is information: below expected and above expected are different
    findings, and an absolute value would erase which one this is."""
    from fitos_api.gaps.writer import _percentage_delta

    worse = _percentage_delta(0.40, 0.02)
    better = _percentage_delta(0.01, 0.02)
    assert worse is not None and worse > 0
    assert better is not None and better < 0


def test_percentage_delta_is_a_ratio_not_a_percentage() -> None:
    """Stored as a ratio so the display layer owns the formatting; storing 1900
    for "1900%" makes every consumer guess which convention this column uses."""
    from fitos_api.gaps.writer import _percentage_delta

    assert _percentage_delta(0.04, 0.02) == pytest.approx(1.0)
