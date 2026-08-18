"""The first two detector classes.

`source_mismatch` is the Stock Truth Gap, the detector the vertical slice is
built around. `ratio_threshold` is the general-purpose one the other packs
reuse. Between them they exercise every framework behaviour a detector can get
wrong, so the remaining ten classes have a pattern to follow rather than a blank
page.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from fitos_worker.detectors.base import (
    DetectorContext,
    MetricReading,
    ObservationWindow,
    ScopeType,
    Severity,
    Unit,
    candidate_fingerprint,
    utc,
)
from fitos_worker.detectors.confidence import ConfidenceBand
from fitos_worker.detectors.ratio_threshold import (
    Direction,
    RatioThresholdConfig,
    RatioThresholdDetector,
)
from fitos_worker.detectors.source_mismatch import (
    SourceMismatchConfig,
    SourceMismatchDetector,
)

RULE = UUID("11111111-1111-1111-1111-111111111111")
WINDOW = ObservationWindow(start=utc(2026, 8, 1), end=utc(2026, 8, 2))
CONTEXT = DetectorContext(
    organization_id=UUID("22222222-2222-2222-2222-222222222222"),
    window=WINDOW,
    as_of=WINDOW.end,
)


def stock_reading(
    *,
    scope: str = "store-1",
    rate: str | None = "0.40",
    denominator: int | None = 100,
    source_max: object = None,
) -> MetricReading:
    return MetricReading(
        metric_key="stock_discrepancy_rate",
        metric_version=1,
        query_hash="deadbeef",
        dimensions={"location_id": scope},
        value=Decimal(rate) if rate is not None else None,
        denominator=denominator,
        captured_at=utc(2026, 8, 2),
        source_max_timestamp=source_max,  # type: ignore[arg-type]
    )


def mismatch(**overrides: object) -> SourceMismatchDetector:
    config: dict[str, object] = {
        "rule_id": RULE,
        "version": 1,
        # A stand-in pack. The detector class is generic, so these tests supply
        # their own vocabulary rather than importing a real pack — a core test
        # that depended on `packs/retail` would invert the contract it is
        # supposed to protect.
        "pack_key": "test_pack",
        "gap_type": "stock_truth_mismatch",
        "canonical_entity": "fact_stock_count",
        "action_playbook_id": "test_pack.stock_truth.recount",
        "title_template": ("Stock records and counts disagree at {scope_id} ({rate} of checks)"),
        "summary_template": (
            "{rate} of {observations} stock checks in this window found a quantity "
            "different from the inventory record. The two sources disagree; which one "
            "is right is not established by this metric."
        ),
        "action_key": "recount_location",
        "action_title": "Recount the affected variants",
        "action_rationale": (
            "Confirms whether the disagreement is in the count or in the inventory "
            "record before anything is adjusted."
        ),
    }
    config.update(overrides)
    return SourceMismatchDetector(SourceMismatchConfig(**config))  # type: ignore[arg-type]


# --- source mismatch: when it fires -----------------------------------------


def test_a_discrepancy_above_threshold_produces_a_gap() -> None:
    result = mismatch().run([stock_reading()], CONTEXT)

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.gap_type == "stock_truth_mismatch"
    assert candidate.scope_type is ScopeType.LOCATION
    assert candidate.scope_id == "store-1"
    assert candidate.observed_value == Decimal("0.40")
    assert candidate.unit is Unit.RATIO


def test_a_discrepancy_at_or_below_threshold_is_silent() -> None:
    below = mismatch(threshold_rate=Decimal("0.05")).run([stock_reading(rate="0.04")], CONTEXT)
    at = mismatch(threshold_rate=Decimal("0.05")).run([stock_reading(rate="0.05")], CONTEXT)

    assert below.candidates == ()
    assert at.candidates == ()


def test_it_compares_against_the_expected_rate_not_zero() -> None:
    """A detector anchored at zero fires on every location in the estate and is
    muted within a week."""
    candidate = mismatch().run([stock_reading()], CONTEXT).candidates[0]

    assert candidate.expected_value == Decimal("0.02")
    assert candidate.expected_value != 0


def test_a_null_rate_is_not_treated_as_zero() -> None:
    """A null rate means an absent denominator. Reading it as zero would report
    every location with no counts as perfectly accurate."""
    result = mismatch().run([stock_reading(rate=None)], CONTEXT)
    assert result.candidates == ()


def test_a_thin_sample_produces_no_gap_at_all() -> None:
    """Two counts, one of which disagreed, is a 50% rate and means nothing."""
    result = mismatch(minimum_observations=30).run(
        [stock_reading(rate="0.50", denominator=2)], CONTEXT
    )

    assert result.candidates == ()
    assert result.insufficient_readings == 1


# --- source mismatch: severity ----------------------------------------------


@pytest.mark.parametrize(
    ("rate", "expected"),
    [
        ("0.06", Severity.MEDIUM),
        ("0.14", Severity.MEDIUM),
        ("0.15", Severity.HIGH),
        ("0.29", Severity.HIGH),
        ("0.30", Severity.CRITICAL),
        ("0.90", Severity.CRITICAL),
    ],
)
def test_severity_steps_with_the_rate(rate: str, expected: Severity) -> None:
    candidate = mismatch().run([stock_reading(rate=rate)], CONTEXT).candidates[0]
    assert candidate.severity is expected


def test_severity_is_not_derived_from_exposure() -> None:
    """A £40 gap in a safety-critical process outranks a £4,000 discretionary
    one; collapsing the two orderings is how a ledger gets sorted by revenue and
    ignored by the people who could fix things."""
    small_estate = mismatch().run([stock_reading(rate="0.40", denominator=40)], CONTEXT)
    large_estate = mismatch().run([stock_reading(rate="0.40", denominator=4000)], CONTEXT)

    assert small_estate.candidates[0].severity is large_estate.candidates[0].severity
    assert (
        small_estate.candidates[0].exposure.base_minor  # type: ignore[union-attr]
        < large_estate.candidates[0].exposure.base_minor  # type: ignore[union-attr]
    )


# --- source mismatch: exposure ----------------------------------------------


def test_the_exposure_is_modelled_and_says_so() -> None:
    """The margin is an assumption, so the whole figure is modelled."""
    candidate = mismatch().run([stock_reading()], CONTEXT).candidates[0]
    exposure = candidate.exposure

    assert exposure is not None
    assert exposure.is_modelled
    assert "modelled_exposure" in candidate.reason_codes


def test_the_exposure_records_both_of_its_inputs() -> None:
    exposure = mismatch().run([stock_reading()], CONTEXT).candidates[0].exposure
    assert exposure is not None

    keys = {a["key"] for a in exposure.assumptions}
    assert keys == {"discrepant_checks", "unit_margin_minor"}


def test_the_exposure_arithmetic_is_the_discrepant_count_times_the_margin_band() -> None:
    exposure = (
        mismatch()
        .run([stock_reading(rate="0.40", denominator=100)], CONTEXT)
        .candidates[0]
        .exposure
    )
    assert exposure is not None

    assert exposure.low_minor == 40 * 150
    assert exposure.base_minor == 40 * 220
    assert exposure.high_minor == 40 * 310
    assert exposure.currency == "GBP"


def test_the_exposure_never_claims_savings() -> None:
    exposure = mismatch().run([stock_reading()], CONTEXT).candidates[0].exposure
    assert exposure is not None
    assert "saving" not in exposure.describe().lower()


def test_the_confidence_band_travels_onto_the_exposure() -> None:
    """A confident-looking money range beside an unconfident gap is a
    contradiction the reader has to resolve themselves."""
    candidate = mismatch().run([stock_reading()], CONTEXT).candidates[0]
    assert candidate.exposure is not None
    # `compute_exposure` may only lower it, never raise it.
    order = [ConfidenceBand.LOW, ConfidenceBand.MEDIUM, ConfidenceBand.HIGH]
    assert order.index(candidate.exposure.confidence_band) <= order.index(candidate.confidence.band)


# --- source mismatch: the copy ----------------------------------------------


FORBIDDEN_CAUSAL_WORDS = (
    "shrinkage",
    "theft",
    "stolen",
    "because",
    "caused",
    "due to",
    "miscount",
    "fraud",
)


def test_the_copy_never_states_a_cause() -> None:
    """The metric establishes a disagreement. It does not establish why."""
    candidate = mismatch().run([stock_reading()], CONTEXT).candidates[0]
    text = f"{candidate.title} {candidate.summary}".lower()

    for word in FORBIDDEN_CAUSAL_WORDS:
        assert word not in text, f"{word!r} appears in the gap copy"


def test_the_recommended_action_is_an_investigation_not_a_diagnosis() -> None:
    candidate = mismatch().run([stock_reading()], CONTEXT).candidates[0]
    action = candidate.recommended_actions[0]

    assert action["key"] == "recount_location"
    assert action["playbook_id"]
    for word in FORBIDDEN_CAUSAL_WORDS:
        assert word not in action["rationale"].lower()


def test_the_title_names_the_scope_and_the_rate() -> None:
    candidate = mismatch().run([stock_reading(scope="store-42", rate="0.40")], CONTEXT)
    assert "store-42" in candidate.candidates[0].title
    assert "40.0%" in candidate.candidates[0].title


# --- source mismatch: evidence and freshness --------------------------------


def test_every_candidate_carries_resolvable_evidence() -> None:
    candidate = mismatch().run([stock_reading()], CONTEXT).candidates[0]
    ref = candidate.evidence[0]

    assert ref.metric_key == "stock_discrepancy_rate"
    assert ref.metric_version == 1
    assert ref.query_hash == "deadbeef"
    assert ref.observation_window == WINDOW.to_json()
    assert ref.query_parameters == {"location_id": "store-1"}


def test_freshness_is_measured_from_the_window_end_not_the_write_time() -> None:
    stale = stock_reading(source_max=utc(2026, 7, 30))
    candidate = mismatch().run([stale], CONTEXT).candidates[0]

    assert candidate.data_freshness_seconds == 3 * 86_400


def test_an_unknown_source_timestamp_leaves_freshness_null_and_drops_the_component() -> None:
    """Null, not zero. A source whose recency is unknown is not a fresh source,
    and scoring it as one would be the most flattering possible guess."""
    candidate = mismatch().run([stock_reading(source_max=None)], CONTEXT).candidates[0]

    assert candidate.data_freshness_seconds is None
    assert "freshness" in candidate.confidence.dropped


def test_a_stale_source_lowers_the_confidence() -> None:
    fresh = mismatch().run([stock_reading(source_max=utc(2026, 8, 2))], CONTEXT)
    stale = mismatch().run([stock_reading(source_max=utc(2026, 6, 1))], CONTEXT)

    assert stale.candidates[0].confidence.score < fresh.candidates[0].confidence.score


# --- source mismatch: replay ------------------------------------------------


def test_the_detector_is_replayable() -> None:
    first = mismatch().run([stock_reading(), stock_reading(scope="store-2")], CONTEXT)
    second = mismatch().run([stock_reading(scope="store-2"), stock_reading()], CONTEXT)

    assert [candidate_fingerprint(c) for c in first.candidates] == [
        candidate_fingerprint(c) for c in second.candidates
    ]


def test_a_threshold_change_changes_the_config_fingerprint() -> None:
    assert (
        mismatch().config.fingerprint()
        != mismatch(threshold_rate=Decimal("0.08")).config.fingerprint()
    )


# --- ratio threshold --------------------------------------------------------


def ratio_reading(
    *, scope: str = "store-1", value: str | None = "0.30", denominator: int | None = 500
) -> MetricReading:
    return MetricReading(
        metric_key="conversion_rate",
        metric_version=2,
        query_hash="cafe",
        dimensions={"location_id": scope},
        value=Decimal(value) if value is not None else None,
        denominator=denominator,
        captured_at=utc(2026, 8, 2),
    )


def ratio(**overrides: object) -> RatioThresholdDetector:
    config: dict[str, object] = {
        "rule_id": RULE,
        "version": 1,
        "pack_key": "retail_omnichannel",
        "gap_type": "conversion_below_band",
        "metric_name": "Conversion rate",
        "expected_value": Decimal("0.50"),
        "lower_bound": Decimal("0.40"),
        "direction": Direction.BELOW,
    }
    config.update(overrides)
    return RatioThresholdDetector(RatioThresholdConfig(**config))  # type: ignore[arg-type]


def test_a_ratio_below_its_lower_bound_fires() -> None:
    candidate = ratio().run([ratio_reading(value="0.30")], CONTEXT).candidates[0]

    assert candidate.gap_type == "conversion_below_band"
    assert candidate.observed_value == Decimal("0.30")
    assert "ratio_below_band" in candidate.reason_codes


def test_a_ratio_inside_the_band_is_silent() -> None:
    assert ratio().run([ratio_reading(value="0.45")], CONTEXT).candidates == ()


def test_a_below_rule_ignores_a_high_value() -> None:
    """Both directions are real, and a detector that guesses gets one of them
    backwards silently."""
    assert ratio().run([ratio_reading(value="0.95")], CONTEXT).candidates == ()


def test_an_above_rule_fires_on_a_high_value() -> None:
    returns = ratio(
        gap_type="return_rate_above_band",
        metric_name="Return rate",
        expected_value=Decimal("0.05"),
        upper_bound=Decimal("0.10"),
        lower_bound=None,
        direction=Direction.ABOVE,
    )
    candidate = returns.run([ratio_reading(value="0.22")], CONTEXT).candidates[0]

    assert "ratio_above_band" in candidate.reason_codes


def test_a_null_ratio_is_not_treated_as_zero() -> None:
    """A completeness metric reading null for a source that sent nothing is the
    absence of data, not a 0% ratio."""
    assert ratio().run([ratio_reading(value=None)], CONTEXT).candidates == ()


def test_a_direction_without_its_bound_is_refused_at_config_time() -> None:
    with pytest.raises(ValueError, match="needs a lower_bound"):
        RatioThresholdConfig(
            rule_id=RULE,
            version=1,
            pack_key="p",
            gap_type="g",
            metric_name="m",
            expected_value=Decimal("0.5"),
            direction=Direction.BELOW,
        )


def test_an_inverted_band_is_refused() -> None:
    """No value can satisfy it, so the rule would fire on everything."""
    with pytest.raises(ValueError, match="fire on everything"):
        RatioThresholdConfig(
            rule_id=RULE,
            version=1,
            pack_key="p",
            gap_type="g",
            metric_name="m",
            expected_value=Decimal("0.5"),
            lower_bound=Decimal("0.9"),
            upper_bound=Decimal("0.1"),
        )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0.38", Severity.MEDIUM),
        ("0.30", Severity.HIGH),
        ("0.19", Severity.CRITICAL),
    ],
)
def test_ratio_severity_steps_with_distance_past_the_bound(value: str, expected: Severity) -> None:
    candidate = ratio().run([ratio_reading(value=value)], CONTEXT).candidates[0]
    assert candidate.severity is expected


# --- ratio threshold: exposure is opt-in ------------------------------------


def test_a_ratio_gap_carries_no_money_by_default() -> None:
    """A ratio moving is not money. Inventing a per-unit value to make the gap
    look important is exactly what the exposure rules exist to prevent, and a
    gap with no monetary figure is complete."""
    candidate = ratio().run([ratio_reading()], CONTEXT).candidates[0]

    assert candidate.exposure is None
    assert candidate.currency is None


def test_a_rule_that_declares_a_unit_value_gets_an_exposure() -> None:
    detector = ratio(
        exposure_per_unit_minor=Decimal("1200"),
        exposure_denominator_dimension="sessions",
    )
    candidate = detector.run([ratio_reading(value="0.30", denominator=500)], CONTEXT).candidates[0]

    assert candidate.exposure is not None
    # 20 percentage points short over 500 sessions is 100 units.
    assert candidate.exposure.base_minor == 100 * 1200


def test_half_configured_exposure_is_refused() -> None:
    """The dangerous state: a figure from a denominator nobody chose."""
    with pytest.raises(ValueError, match="not an exposure"):
        RatioThresholdConfig(
            rule_id=RULE,
            version=1,
            pack_key="p",
            gap_type="g",
            metric_name="m",
            expected_value=Decimal("0.5"),
            lower_bound=Decimal("0.4"),
            direction=Direction.BELOW,
            exposure_per_unit_minor=Decimal("1200"),
        )


def test_the_ratio_copy_describes_the_movement_without_explaining_it() -> None:
    candidate = ratio().run([ratio_reading()], CONTEXT).candidates[0]
    text = f"{candidate.title} {candidate.summary}".lower()

    assert "does not establish its cause" in text
    for word in ("because", "caused", "due to"):
        assert word not in text.replace("does not establish its cause", "")


def test_the_ratio_detector_reports_its_configured_gap_type() -> None:
    """Twelve rules share this class; the gap type comes from the rule, not the
    class, or every pack's gaps would land under one type."""
    assert ratio().gap_type == "conversion_below_band"
    assert ratio(gap_type="attach_rate_below_band").gap_type == "attach_rate_below_band"
