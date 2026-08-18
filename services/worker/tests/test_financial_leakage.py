"""Financial leakage.

The only detector whose exposure is observed rather than modelled, and the only
one that has to distinguish three shapes of the same arithmetic. Both are places
where being approximately right produces a confidently wrong number.
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
    utc,
)
from fitos_worker.detectors.confidence import ConfidenceBand
from fitos_worker.detectors.financial_leakage import (
    FinancialLeakageConfig,
    FinancialLeakageDetector,
    LeakageShape,
)

RULE = UUID("11111111-1111-1111-1111-111111111111")
WINDOW = ObservationWindow(start=utc(2026, 8, 1), end=utc(2026, 9, 1))
CONTEXT = DetectorContext(
    organization_id=UUID("22222222-2222-2222-2222-222222222222"),
    window=WINDOW,
    as_of=WINDOW.end,
)


def reading(
    *,
    scope: str = "variant-42",
    margin: str = "0.28",
    prior_margin: str = "0.36",
    revenue: str = "1200000",
    prior_revenue: str = "1000000",
    currency: str = "GBP",
    denominator: int = 800,
    drop: tuple[str, ...] = (),
) -> MetricReading:
    dims = {
        "product_variant_id": scope,
        "margin_rate": margin,
        "prior_margin_rate": prior_margin,
        "revenue_minor": revenue,
        "prior_revenue_minor": prior_revenue,
        "currency": currency,
    }
    for key in drop:
        dims.pop(key, None)
    return MetricReading(
        metric_key="gross_margin_rate",
        metric_version=1,
        query_hash="leak",
        dimensions=dims,
        value=Decimal(margin),
        denominator=denominator,
        captured_at=WINDOW.end,
    )


def detector(**overrides: object) -> FinancialLeakageDetector:
    config: dict[str, object] = {
        "rule_id": RULE,
        "version": 1,
        "pack_key": "test_pack",
        "gap_type": "margin_leakage",
        "canonical_entity": "fact_financial_line",
        "minimum_observations": 30,
    }
    config.update(overrides)
    return FinancialLeakageDetector(FinancialLeakageConfig(**config))  # type: ignore[arg-type]


# --- the shape distinction --------------------------------------------------


def test_revenue_up_and_margin_down_is_the_leak() -> None:
    """Selling more at a worse rate."""
    candidate = detector().run([reading()], CONTEXT).candidates[0]
    assert LeakageShape.REVENUE_UP_MARGIN_DOWN.value in candidate.reason_codes
    assert "while revenue rose" in candidate.summary


def test_revenue_flat_and_margin_down_is_a_cost_problem() -> None:
    candidate = (
        detector().run([reading(revenue="1000000", prior_revenue="1000000")], CONTEXT).candidates[0]
    )
    assert LeakageShape.REVENUE_FLAT_MARGIN_DOWN.value in candidate.reason_codes
    assert "flat revenue" in candidate.summary


def test_revenue_down_is_not_raised_by_this_rule_by_default() -> None:
    """A demand problem this detector would misattribute. Raising it here puts
    a margin explanation on a volume problem."""
    assert (
        detector().run([reading(revenue="600000", prior_revenue="1000000")], CONTEXT).candidates
        == ()
    )


def test_a_pack_can_opt_into_the_revenue_down_shape() -> None:
    candidate = (
        detector(
            shapes=[
                LeakageShape.REVENUE_UP_MARGIN_DOWN,
                LeakageShape.REVENUE_FLAT_MARGIN_DOWN,
                LeakageShape.REVENUE_DOWN_MARGIN_DOWN,
            ]
        )
        .run([reading(revenue="600000", prior_revenue="1000000")], CONTEXT)
        .candidates[0]
    )
    assert LeakageShape.REVENUE_DOWN_MARGIN_DOWN.value in candidate.reason_codes


def test_the_flat_band_keeps_the_shape_stable_across_noise() -> None:
    """Without a band, ordinary noise reclassifies the shape period to period
    and the reason codes become useless."""
    barely_up = (
        detector().run([reading(revenue="1010000", prior_revenue="1000000")], CONTEXT).candidates[0]
    )
    barely_down = (
        detector().run([reading(revenue="990000", prior_revenue="1000000")], CONTEXT).candidates[0]
    )

    assert LeakageShape.REVENUE_FLAT_MARGIN_DOWN.value in barely_up.reason_codes
    assert LeakageShape.REVENUE_FLAT_MARGIN_DOWN.value in barely_down.reason_codes


def test_no_prior_revenue_is_flat_not_infinite_growth() -> None:
    """A naive ratio would produce infinite growth and classify a first-period
    product as the worst leak in the estate."""
    candidate = (
        detector().run([reading(revenue="1200000", prior_revenue="0")], CONTEXT).candidates[0]
    )
    assert LeakageShape.REVENUE_FLAT_MARGIN_DOWN.value in candidate.reason_codes


# --- firing and severity ----------------------------------------------------


def test_a_margin_holding_steady_is_silent() -> None:
    assert detector().run([reading(margin="0.355", prior_margin="0.36")], CONTEXT).candidates == ()


def test_a_rising_margin_is_silent() -> None:
    assert detector().run([reading(margin="0.42", prior_margin="0.36")], CONTEXT).candidates == ()


@pytest.mark.parametrize(
    ("margin", "expected"),
    [("0.33", Severity.MEDIUM), ("0.30", Severity.HIGH), ("0.24", Severity.CRITICAL)],
)
def test_severity_steps_with_the_margin_points_lost(margin: str, expected: Severity) -> None:
    candidate = detector().run([reading(margin=margin, prior_margin="0.36")], CONTEXT).candidates[0]
    assert candidate.severity is expected


def test_the_scope_is_the_product_variant() -> None:
    candidate = detector().run([reading(scope="variant-99")], CONTEXT).candidates[0]
    assert candidate.scope_type is ScopeType.PRODUCT_VARIANT
    assert candidate.scope_id == "variant-99"


# --- the exposure is observed -----------------------------------------------


def test_the_exposure_is_observed_not_modelled() -> None:
    """The only one in the system. Revenue and margin points are both real
    ledger figures, so the interval collapses to a point and says so."""
    exposure = detector().run([reading()], CONTEXT).candidates[0].exposure

    assert exposure is not None
    assert not exposure.is_modelled
    assert "modelled_exposure" not in exposure.reason_codes
    assert exposure.low_minor == exposure.base_minor == exposure.high_minor


def test_the_exposure_is_revenue_times_the_margin_points_lost() -> None:
    exposure = (
        detector()
        .run([reading(revenue="1200000", margin="0.28", prior_margin="0.36")], CONTEXT)
        .candidates[0]
        .exposure
    )

    assert exposure is not None
    # 0.08 of 1,200,000 minor units.
    assert exposure.base_minor == 96_000


def test_both_exposure_inputs_are_recorded_as_observed() -> None:
    exposure = detector().run([reading()], CONTEXT).candidates[0].exposure
    assert exposure is not None
    assert {a["key"] for a in exposure.assumptions} == {"revenue_minor", "margin_points_lost"}
    assert all(a["kind"] == "observed" for a in exposure.assumptions)


def test_the_exposure_never_claims_savings() -> None:
    exposure = detector().run([reading()], CONTEXT).candidates[0].exposure
    assert exposure is not None
    assert "saving" not in exposure.describe().lower()


# --- currency ---------------------------------------------------------------


def test_a_missing_currency_is_refused_not_defaulted() -> None:
    """Summing minor units across currencies is meaningless, and a guessed
    currency is how that happens without anybody choosing it."""
    result = detector().run([reading(drop=("currency",))], CONTEXT)
    assert result.candidates == ()
    assert "missing ['currency']" in result.errors[0]


def test_a_non_iso_currency_is_refused() -> None:
    result = detector().run([reading(currency="pounds")], CONTEXT)
    assert result.candidates == ()
    assert "ISO 4217" in result.errors[0]


def test_the_currency_travels_onto_the_exposure() -> None:
    exposure = detector().run([reading(currency="eur")], CONTEXT).candidates[0].exposure
    assert exposure is not None
    assert exposure.currency == "EUR"


# --- partial readings -------------------------------------------------------


@pytest.mark.parametrize(
    "field", ["revenue_minor", "prior_revenue_minor", "margin_rate", "prior_margin_rate"]
)
def test_a_partial_ledger_reading_is_refused(field: str) -> None:
    """A margin movement computed from three of five figures produces a number
    that looks exactly like a real one."""
    result = detector().run([reading(drop=(field,))], CONTEXT)
    assert result.candidates == ()
    assert not result.succeeded
    assert field in result.errors[0]


def test_a_thin_sample_is_refused_before_the_detector_sees_it() -> None:
    result = detector(minimum_observations=100).run([reading(denominator=20)], CONTEXT)
    assert result.candidates == ()
    assert result.insufficient_readings == 1


# --- the copy and the confidence --------------------------------------------


def test_the_copy_names_what_moved_without_explaining_it() -> None:
    """Discounting, mix shift, supplier cost and returns are indistinguishable
    in a margin rate."""
    candidate = detector().run([reading()], CONTEXT).candidates[0]
    assert "none of them is established here" in candidate.summary
    for word in ("because", "caused by", "due to", "driven by"):
        assert word not in candidate.summary.lower()


def test_the_confidence_is_high_because_the_arithmetic_is_observed() -> None:
    """Unlike attribution. De-confidencing an observation to signal caution
    about its interpretation would misreport the observation."""
    candidate = detector().run([reading()], CONTEXT).candidates[0]
    assert candidate.confidence.band is ConfidenceBand.HIGH
    assert "attribution_limited" not in candidate.confidence.reason_codes


def test_the_evidence_is_marked_confidential() -> None:
    """Margin figures are not internal-by-default. The API filters references a
    caller may not resolve, and it can only do that if the classification is on
    the reference."""
    candidate = detector().run([reading()], CONTEXT).candidates[0]
    assert candidate.evidence[0].sensitivity_classification == "confidential"
