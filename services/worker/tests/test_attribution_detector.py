"""Attribution comparison — low confidence by construction.

The cap is the point of this class. A correlation between spend and outcome does
not establish the link, and the tests here are mostly about proving the detector
cannot be talked into saying otherwise: not by a large sample, not by a fresh
source, and not by copy that implies more than the model supports.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from fitos_worker.detectors.attribution import (
    FORBIDDEN_CAUSAL_WORDS,
    AttributionConfig,
    AttributionDetector,
    AttributionMethod,
)
from fitos_worker.detectors.base import (
    DetectorContext,
    MetricReading,
    ObservationWindow,
    ScopeType,
    Severity,
    utc,
)
from fitos_worker.detectors.confidence import ConfidenceBand

RULE = UUID("11111111-1111-1111-1111-111111111111")
WINDOW = ObservationWindow(start=utc(2026, 8, 1), end=utc(2026, 8, 8))
CONTEXT = DetectorContext(
    organization_id=UUID("22222222-2222-2222-2222-222222222222"),
    window=WINDOW,
    as_of=WINDOW.end,
)


def reading(
    *, scope: str = "campaign-spring", value: str | None = "0.60", denominator: int | None = 400
) -> MetricReading:
    return MetricReading(
        metric_key="attributable_orders_per_pound",
        metric_version=1,
        query_hash="attr",
        dimensions={"campaign_id": scope},
        value=Decimal(value) if value is not None else None,
        denominator=denominator,
        captured_at=WINDOW.end,
    )


def detector(**overrides: object) -> AttributionDetector:
    config: dict[str, object] = {
        "rule_id": RULE,
        "version": 1,
        "pack_key": "test_pack",
        "gap_type": "campaign_below_baseline",
        "canonical_entity": "fact_campaign_spend",
        "metric_name": "Attributable orders per pound",
        "attribution_method": AttributionMethod.LAST_TOUCH,
        "expected_ratio": Decimal("1.00"),
        "threshold_ratio": Decimal("0.80"),
    }
    config.update(overrides)
    return AttributionDetector(AttributionConfig(**config))  # type: ignore[arg-type]


# --- the cap ----------------------------------------------------------------


def test_the_confidence_band_is_capped_at_medium() -> None:
    candidate = detector().run([reading()], CONTEXT).candidates[0]
    assert candidate.confidence.band is ConfidenceBand.MEDIUM
    assert "attribution_limited" in candidate.confidence.reason_codes


def test_a_large_sample_cannot_raise_the_band() -> None:
    """No sample size establishes causation. That is the whole design."""
    for observations in (100, 1_000, 50_000, 1_000_000):
        candidate = detector().run([reading(denominator=observations)], CONTEXT).candidates[0]
        assert candidate.confidence.band is not ConfidenceBand.HIGH


def test_the_cap_is_applied_by_the_confidence_model_not_by_this_detector() -> None:
    """A cap the detector applies itself is one a future edit can reorder away.

    `score_confidence(is_attribution_based=True)` applies it after every other
    calculation, so this test is really asserting the detector passes the flag.
    """
    candidate = detector().run([reading(denominator=100_000)], CONTEXT).candidates[0]
    assert "attribution-based" in candidate.confidence.caps_applied


def test_the_cap_does_not_raise_a_low_band() -> None:
    """A ceiling, not an assignment."""
    thin = (
        detector(minimum_observations=1000).run([reading(denominator=1000)], CONTEXT).candidates[0]
    )
    assert thin.confidence.band in (ConfidenceBand.LOW, ConfidenceBand.MEDIUM)


# --- the declared method ----------------------------------------------------


def test_the_method_must_be_declared() -> None:
    """An attribution model chosen by omission is worse than a contested one."""
    with pytest.raises(ValueError, match="attribution_method"):
        AttributionConfig(  # type: ignore[call-arg]
            rule_id=RULE,
            version=1,
            pack_key="p",
            gap_type="g",
            canonical_entity="e",
            metric_name="m",
            expected_ratio=Decimal("1.0"),
            threshold_ratio=Decimal("0.8"),
        )


def test_the_method_travels_with_the_gap() -> None:
    candidate = (
        detector(attribution_method=AttributionMethod.LINEAR)
        .run([reading()], CONTEXT)
        .candidates[0]
    )
    assert "method_linear" in candidate.reason_codes
    assert "linear" in candidate.summary


def test_an_unknown_method_is_refused() -> None:
    with pytest.raises(ValueError, match="attribution_method"):
        AttributionConfig(
            rule_id=RULE,
            version=1,
            pack_key="p",
            gap_type="g",
            canonical_entity="e",
            metric_name="m",
            attribution_method="whatever_marketing_said",  # type: ignore[arg-type]
            expected_ratio=Decimal("1.0"),
            threshold_ratio=Decimal("0.8"),
        )


# --- the copy ---------------------------------------------------------------


def test_the_copy_makes_no_causal_claim() -> None:
    """Only a controlled_test outcome may use causal language anywhere in this
    product, and this detector is definitionally not one."""
    candidate = detector().run([reading()], CONTEXT).candidates[0]
    text = f"{candidate.title} {candidate.summary}".lower()

    for word in FORBIDDEN_CAUSAL_WORDS:
        assert word not in text, f"{word!r} appears in an attribution gap"


def test_the_copy_says_what_the_model_actually_does() -> None:
    candidate = detector().run([reading()], CONTEXT).candidates[0]
    assert "coincides with" in candidate.summary
    assert "assigns credit, it does not establish" in candidate.summary


def test_the_forbidden_word_list_is_not_empty() -> None:
    """A copy check against an empty list passes any wording at all."""
    assert len(FORBIDDEN_CAUSAL_WORDS) >= 5


# --- firing and severity ----------------------------------------------------


def test_a_ratio_at_or_above_threshold_is_silent() -> None:
    assert detector().run([reading(value="0.80")], CONTEXT).candidates == ()
    assert detector().run([reading(value="1.20")], CONTEXT).candidates == ()


def test_a_null_ratio_is_not_treated_as_zero() -> None:
    assert detector().run([reading(value=None)], CONTEXT).candidates == ()


def test_severity_is_never_critical_without_an_explicit_threshold() -> None:
    """A campaign underperforming under a contested model is not an emergency,
    and ranking it as one crowds out findings that are."""
    candidate = detector().run([reading(value="0.01")], CONTEXT).candidates[0]
    assert candidate.severity is Severity.MEDIUM


def test_severity_steps_only_where_the_pack_declares_it() -> None:
    tuned = detector(severity_high_ratio=Decimal("0.50"), severity_critical_ratio=Decimal("0.20"))
    assert tuned.run([reading(value="0.70")], CONTEXT).candidates[0].severity is Severity.MEDIUM
    assert tuned.run([reading(value="0.40")], CONTEXT).candidates[0].severity is Severity.HIGH
    assert tuned.run([reading(value="0.10")], CONTEXT).candidates[0].severity is Severity.CRITICAL


def test_the_scope_is_the_campaign() -> None:
    candidate = detector().run([reading(scope="campaign-autumn")], CONTEXT).candidates[0]
    assert candidate.scope_type is ScopeType.CAMPAIGN
    assert candidate.scope_id == "campaign-autumn"


# --- exposure ---------------------------------------------------------------


def test_no_exposure_unless_the_pack_declares_an_attributable_share() -> None:
    """What the spend produced is not observed. Without a stated share there is
    no honest figure, and inventing one is what the exposure rules prevent."""
    assert detector().run([reading()], CONTEXT).candidates[0].exposure is None


def test_a_declared_share_produces_a_modelled_interval() -> None:
    candidate = (
        detector(
            attributable_share_low=Decimal("0.20"),
            attributable_share_base=Decimal("0.40"),
            attributable_share_high=Decimal("0.70"),
        )
        .run([reading(value="0.60", denominator=400)], CONTEXT)
        .candidates[0]
    )

    exposure = candidate.exposure
    assert exposure is not None
    assert exposure.is_modelled
    # 0.40 short over 400 observations is 160 units.
    assert exposure.low_minor == int(160 * 0.20)
    assert exposure.high_minor == int(160 * 0.70)


def test_the_attribution_assumption_is_recorded_on_the_exposure() -> None:
    """A figure whose attribution model is not written down cannot be argued
    with, which is the same as not being trustworthy."""
    candidate = (
        detector(
            attribution_method=AttributionMethod.POSITION_BASED,
            attributable_share_low=Decimal("0.20"),
            attributable_share_base=Decimal("0.40"),
            attributable_share_high=Decimal("0.70"),
        )
        .run([reading()], CONTEXT)
        .candidates[0]
    )

    assert candidate.exposure is not None
    share = next(a for a in candidate.exposure.assumptions if a["key"] == "attributable_share")
    assert "position_based" in share["statement"]
    assert "position_based" in share["source"]


def test_a_wide_share_band_forces_the_exposure_band_to_low() -> None:
    """The interval is itself a confidence statement, and an attribution share
    spanning an order of magnitude says the model does not know."""
    candidate = (
        detector(
            attributable_share_low=Decimal("0.05"),
            attributable_share_base=Decimal("0.40"),
            attributable_share_high=Decimal("0.90"),
        )
        .run([reading()], CONTEXT)
        .candidates[0]
    )

    assert candidate.exposure is not None
    assert candidate.exposure.confidence_band is ConfidenceBand.LOW
    assert "wide_exposure_interval" in candidate.exposure.reason_codes


def test_half_declared_share_bounds_produce_no_exposure() -> None:
    """Rather than a figure built from one bound and two guesses."""
    candidate = (
        detector(attributable_share_base=Decimal("0.40")).run([reading()], CONTEXT).candidates[0]
    )
    assert candidate.exposure is None
