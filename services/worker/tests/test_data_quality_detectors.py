"""Freshness, completeness and schema drift.

The suppression link is what these are for: a data-quality gap on a source
de-confidences the business gaps built on it. The last section of this file
proves that link works end to end through the pipeline, because a
data-quality family that fires correctly and suppresses nothing is exactly as
useless as one that does not fire.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from fitos_worker.detectors.base import (
    DetectorContext,
    DetectorRunResult,
    MetricReading,
    ObservationWindow,
    Severity,
    Unit,
    utc,
)
from fitos_worker.detectors.confidence import ConfidenceBand
from fitos_worker.detectors.data_quality import (
    CompletenessConfig,
    CompletenessDetector,
    FreshnessConfig,
    FreshnessDetector,
    SchemaDriftConfig,
    SchemaDriftDetector,
)
from fitos_worker.detectors.pipeline import SUPPRESSED_REASON_CODE, OpenGap, suppress
from fitos_worker.detectors.ratio_threshold import (
    Direction,
    RatioThresholdConfig,
    RatioThresholdDetector,
)

RULE = UUID("11111111-1111-1111-1111-111111111111")
WINDOW = ObservationWindow(start=utc(2026, 8, 1), end=utc(2026, 8, 2))
CONTEXT = DetectorContext(
    organization_id=UUID("22222222-2222-2222-2222-222222222222"),
    window=WINDOW,
    as_of=WINDOW.end,
)
HOURLY = 3600.0


def reading(
    *,
    metric_key: str = "source_freshness",
    source: str = "csv_upload",
    value: str | None = None,
    denominator: int | None = None,
    age_hours: float | None = None,
    dimensions: dict[str, str] | None = None,
) -> MetricReading:
    dims = {"source_key": source}
    if dimensions:
        dims.update(dimensions)
    return MetricReading(
        metric_key=metric_key,
        metric_version=1,
        query_hash="dq-hash",
        dimensions=dims,
        value=Decimal(value) if value is not None else None,
        denominator=denominator,
        captured_at=WINDOW.end,
        source_max_timestamp=(
            WINDOW.end - timedelta(hours=age_hours) if age_hours is not None else None
        ),
    )


def freshness(**overrides: object) -> FreshnessDetector:
    config: dict[str, object] = {
        "rule_id": RULE,
        "version": 1,
        "pack_key": "test_pack",
        "expected_latency_seconds": HOURLY,
    }
    config.update(overrides)
    return FreshnessDetector(FreshnessConfig(**config))  # type: ignore[arg-type]


def completeness(**overrides: object) -> CompletenessDetector:
    config: dict[str, object] = {"rule_id": RULE, "version": 1, "pack_key": "test_pack"}
    config.update(overrides)
    return CompletenessDetector(CompletenessConfig(**config))  # type: ignore[arg-type]


def drift(**overrides: object) -> SchemaDriftDetector:
    config: dict[str, object] = {"rule_id": RULE, "version": 1, "pack_key": "test_pack"}
    config.update(overrides)
    return SchemaDriftDetector(SchemaDriftConfig(**config))  # type: ignore[arg-type]


# --- freshness --------------------------------------------------------------


def test_a_source_inside_its_declared_cadence_is_silent() -> None:
    assert freshness().run([reading(age_hours=1.5)], CONTEXT).candidates == ()


def test_a_source_past_its_tolerance_raises_a_gap() -> None:
    result = freshness().run([reading(age_hours=6)], CONTEXT)

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.gap_type == "source_freshness_breach"
    assert candidate.unit is Unit.SECONDS
    assert candidate.observed_value == Decimal(6 * 3600)
    assert candidate.expected_value == Decimal(3600)
    assert candidate.data_freshness_seconds == 6 * 3600


def test_freshness_is_measured_against_the_declared_cadence_not_a_constant() -> None:
    """A feed promising hourly and one promising weekly are both healthy at ages
    that differ by two orders of magnitude."""
    six_hours = reading(age_hours=6)
    assert freshness(expected_latency_seconds=HOURLY).run([six_hours], CONTEXT).candidates
    assert (
        not freshness(expected_latency_seconds=HOURLY * 24 * 7).run([six_hours], CONTEXT).candidates
    )


def test_a_source_that_has_never_reported_is_not_a_freshness_gap() -> None:
    """Unknown recency is a different finding. Calling it "0 seconds old" would
    be the most flattering possible guess."""
    assert freshness().run([reading(age_hours=None)], CONTEXT).candidates == ()


@pytest.mark.parametrize(
    ("hours", "expected"),
    [(3, Severity.MEDIUM), (5, Severity.HIGH), (13, Severity.CRITICAL)],
)
def test_freshness_severity_steps_with_how_overdue_it_is(hours: float, expected: Severity) -> None:
    candidate = freshness().run([reading(age_hours=hours)], CONTEXT).candidates[0]
    assert candidate.severity is expected


def test_a_freshness_gap_carries_no_exposure() -> None:
    """A late feed is not money. Attaching a figure would mean inventing one."""
    candidate = freshness().run([reading(age_hours=6)], CONTEXT).candidates[0]
    assert candidate.exposure is None
    assert candidate.currency is None


def test_a_freshness_gap_is_confident_and_honestly_so() -> None:
    """ "This timestamp is older than that timestamp" is an observation, not an
    inference. Sample size and source agreement are dropped rather than guessed."""
    candidate = freshness().run([reading(age_hours=6)], CONTEXT).candidates[0]
    assert candidate.confidence.band is ConfidenceBand.HIGH
    assert "sample_size" in candidate.confidence.dropped
    assert "source_agreement" in candidate.confidence.dropped


def test_freshness_has_no_sample_minimum() -> None:
    """One late delivery is the whole finding."""
    assert freshness().config.minimum_observations == 0
    assert freshness().run([reading(age_hours=6, denominator=None)], CONTEXT).candidates


def test_the_freshness_copy_states_the_consequence_not_a_cause() -> None:
    candidate = freshness().run([reading(age_hours=6)], CONTEXT).candidates[0]
    text = f"{candidate.title} {candidate.summary}".lower()
    assert "older world" in text
    for word in ("because", "caused", "outage", "broken"):
        assert word not in text


# --- completeness -----------------------------------------------------------


def test_a_complete_source_is_silent() -> None:
    assert completeness().run([reading(value="1.00", denominator=500)], CONTEXT).candidates == ()


def test_an_incomplete_source_raises_a_gap() -> None:
    candidate = completeness().run([reading(value="0.80", denominator=500)], CONTEXT).candidates[0]

    assert candidate.gap_type == "data_completeness_drop"
    assert candidate.observed_value == Decimal("0.80")
    assert "100 of 500" in candidate.summary


def test_a_source_that_delivered_nothing_is_not_a_completeness_gap() -> None:
    """No ratio means nothing arrived to measure. That is a freshness or
    connection finding, and reporting 0% complete would double-count it."""
    assert completeness().run([reading(value=None, denominator=0)], CONTEXT).candidates == ()


@pytest.mark.parametrize(
    ("value", "expected"),
    [("0.95", Severity.MEDIUM), ("0.85", Severity.HIGH), ("0.50", Severity.CRITICAL)],
)
def test_completeness_severity_steps_with_how_much_is_missing(
    value: str, expected: Severity
) -> None:
    candidate = completeness().run([reading(value=value, denominator=100)], CONTEXT).candidates[0]
    assert candidate.severity is expected


def test_the_completeness_score_feeds_the_confidence() -> None:
    """A gap about missing data cannot claim full confidence in the measurement
    it made over that same data."""
    poor = completeness().run([reading(value="0.30", denominator=100)], CONTEXT).candidates[0]
    good = completeness().run([reading(value="0.95", denominator=100)], CONTEXT).candidates[0]
    assert poor.confidence.score < good.confidence.score


def test_a_completeness_gap_carries_no_exposure() -> None:
    candidate = completeness().run([reading(value="0.50", denominator=100)], CONTEXT).candidates[0]
    assert candidate.exposure is None


# --- schema drift -----------------------------------------------------------


def _drift_reading(kind: str, field: str = "total_amount") -> MetricReading:
    return reading(
        metric_key="schema_drift",
        dimensions={"drift_kind": kind, "field_name": field},
    )


def test_a_single_drift_occurrence_raises_a_gap() -> None:
    """One unexpected column is a contract change. A rate would average a
    breaking change into nothing."""
    result = drift().run([_drift_reading("removed_field")], CONTEXT)

    assert len(result.candidates) == 1
    assert result.candidates[0].gap_type == "schema_drift"
    assert result.candidates[0].observed_value == Decimal(1)
    assert result.candidates[0].expected_value == Decimal(0)


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("removed_field", Severity.CRITICAL),
        ("type_change", Severity.HIGH),
        ("new_field", Severity.LOW),
    ],
)
def test_drift_severity_reflects_what_broke(kind: str, expected: Severity) -> None:
    """A removed field is critical because everything downstream is now
    computing over nulls it cannot see."""
    candidate = drift().run([_drift_reading(kind)], CONTEXT).candidates[0]
    assert candidate.severity is expected
    assert kind in candidate.reason_codes


def test_a_reading_with_no_drift_is_silent() -> None:
    assert drift().run([reading(metric_key="schema_drift")], CONTEXT).candidates == ()


def test_an_unknown_drift_kind_is_refused_not_guessed() -> None:
    """A severity guessed for an unrecognised drift kind is a number the
    detector invented. The run record carries the error instead."""
    result = drift().run([_drift_reading("field_renamed_probably")], CONTEXT)

    assert result.candidates == ()
    assert not result.succeeded
    assert "unknown drift_kind" in result.errors[0]


def test_the_drift_gap_names_the_affected_field() -> None:
    candidate = drift().run([_drift_reading("type_change", "order_total")].copy(), CONTEXT)
    assert "order_total" in candidate.candidates[0].title


def test_drift_has_no_sample_minimum() -> None:
    assert drift().config.minimum_observations == 0


# --- the suppression link ---------------------------------------------------


def _business_gap() -> DetectorRunResult:
    detector = RatioThresholdDetector(
        RatioThresholdConfig(
            rule_id=RULE,
            version=1,
            pack_key="test_pack",
            gap_type="conversion_below_band",
            metric_name="Conversion rate",
            expected_value=Decimal("0.50"),
            lower_bound=Decimal("0.40"),
            direction=Direction.BELOW,
            scope_dimension="location_id",
        )
    )
    return detector.run(
        [
            MetricReading(
                metric_key="conversion_rate",
                metric_version=1,
                query_hash="conv",
                dimensions={"location_id": "store-1"},
                value=Decimal("0.20"),
                denominator=500,
                captured_at=WINDOW.end,
            )
        ],
        CONTEXT,
    )


def test_a_data_quality_gap_de_confidences_the_business_gap_on_the_same_source() -> None:
    """The reason this family exists as gaps rather than an ops dashboard.

    The link is by contributing source, not by scope: a feed-level freshness
    problem and a store-level conversion problem are scoped differently and are
    still the same story.
    """
    business = _business_gap().candidates[0]
    # The business gap correlates on the metric it read; the data-quality gap
    # names that same metric as a contributing source.
    upstream = OpenGap(
        gap_id=UUID("33333333-3333-3333-3333-333333333333"),
        dedupe_key="dq",
        gap_type="source_freshness_breach",
        scope_type="organization",
        scope_id="conversion_feed",
        status="triaged",
        contributing_sources=frozenset(business.correlation_keys),
    )

    kept, suppressed = suppress([business], open_gaps=[upstream])

    assert SUPPRESSED_REASON_CODE in kept[0].reason_codes
    assert kept[0].confidence.band is ConfidenceBand.LOW
    assert suppressed == ["conversion_below_band:store-1"]


def test_the_business_gap_is_still_shown_not_hidden() -> None:
    """Hiding it would make a data outage look like calm."""
    business = _business_gap().candidates[0]
    upstream = OpenGap(
        gap_id=UUID("33333333-3333-3333-3333-333333333333"),
        dedupe_key="dq",
        gap_type="data_completeness_drop",
        scope_type="organization",
        scope_id="conversion_feed",
        status="detected",
        contributing_sources=frozenset(business.correlation_keys),
    )
    kept, _ = suppress([business], open_gaps=[upstream])

    assert len(kept) == 1
    assert kept[0].gap_type == "conversion_below_band"
    assert kept[0].observed_value == Decimal("0.20"), "the measurement is unchanged"


def test_an_unrelated_data_quality_gap_does_not_suppress() -> None:
    """Otherwise one late feed de-confidences the whole ledger."""
    business = _business_gap().candidates[0]
    unrelated = OpenGap(
        gap_id=UUID("33333333-3333-3333-3333-333333333333"),
        dedupe_key="dq",
        gap_type="source_freshness_breach",
        scope_type="organization",
        scope_id="payroll_feed",
        status="detected",
        contributing_sources=frozenset({"metric:payroll_hours@v1"}),
    )
    kept, suppressed = suppress([business], open_gaps=[unrelated])

    assert suppressed == []
    assert kept[0].reason_codes == business.reason_codes


def test_every_data_quality_gap_type_is_known_to_the_suppression_stage() -> None:
    """A class added here and forgotten in the pipeline suppresses nothing, and
    looks exactly like one that works."""
    from fitos_worker.detectors.pipeline import DATA_QUALITY_GAP_TYPES

    emitted = {
        FreshnessDetector.gap_type,
        CompletenessDetector.gap_type,
        SchemaDriftDetector.gap_type,
    }
    assert emitted <= DATA_QUALITY_GAP_TYPES, (
        f"these fire but suppress nothing: {sorted(emitted - DATA_QUALITY_GAP_TYPES)}"
    )
