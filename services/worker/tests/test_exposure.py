"""Tests for the exposure model.

The rule under test is CLAUDE.md's: *no modelled money without low, base, high,
assumptions and confidence*. Most of these are constructor refusals rather than
calculations, because the point of the module is that producing a bare number is
not possible — and a refusal that nobody has tried to trigger is a refusal
nobody knows works.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest
from fitos_worker.detectors.confidence import ConfidenceBand
from fitos_worker.detectors.exposure import (
    Exposure,
    ExposureError,
    ExposureInput,
    InputKind,
    assumed,
    compute_exposure,
    from_governed_metric,
    observed,
)


def _units() -> ExposureInput:
    return observed("units", "42 units short on 2026-08-01", Decimal(42), "gov_stock_truth@v1")


def _margin() -> ExposureInput:
    return assumed(
        "margin_minor",
        "Contribution margin per unit",
        low=Decimal(200),
        base=Decimal(250),
        high=Decimal(300),
        source="organization_assumption",
    )


# --- the four required parts ------------------------------------------------


def test_an_exposure_without_assumptions_cannot_be_constructed() -> None:
    """A figure whose inputs are not recorded cannot be argued with."""
    with pytest.raises(ExposureError, match="at least one assumption"):
        Exposure(
            low_minor=1000,
            base_minor=2000,
            high_minor=3000,
            currency="GBP",
            formula_key="stock_truth_exposure",
            formula_version=1,
            assumptions=(),
            confidence_band=ConfidenceBand.MEDIUM,
            is_modelled=True,
        )


def test_an_unordered_exposure_cannot_be_constructed() -> None:
    with pytest.raises(ExposureError, match="must be ordered"):
        Exposure(
            low_minor=3000,
            base_minor=2000,
            high_minor=1000,
            currency="GBP",
            formula_key="k",
            formula_version=1,
            assumptions=({"key": "x"},),
            confidence_band=ConfidenceBand.LOW,
            is_modelled=True,
        )


@pytest.mark.parametrize("currency", ["GB", "GBPP", "GB1", ""])
def test_a_non_iso_currency_is_rejected(currency: str) -> None:
    """Summing minor units without knowing the currency is meaningless, so the
    code is not optional and not free text."""
    with pytest.raises(ExposureError, match="ISO 4217"):
        Exposure(
            low_minor=1,
            base_minor=1,
            high_minor=1,
            currency=currency,
            formula_key="k",
            formula_version=1,
            assumptions=({"key": "x"},),
            confidence_band=ConfidenceBand.LOW,
            is_modelled=False,
        )


def test_every_input_becomes_an_assumption_record() -> None:
    """Observed inputs included: "this was measured exactly" is as much a part
    of explaining a figure as "we assumed 35%"."""
    exposure = compute_exposure(
        inputs=[_units(), _margin()],
        currency="GBP",
        formula_key="stock_truth_exposure",
        formula_version=1,
        confidence_band=ConfidenceBand.MEDIUM,
    )

    assert len(exposure.assumptions) == 2
    keys = {a["key"] for a in exposure.assumptions}
    assert keys == {"units", "margin_minor"}
    assert all(a["source"] for a in exposure.assumptions)
    assert all(a["statement"] for a in exposure.assumptions)


def test_the_assumption_record_names_its_provenance() -> None:
    records = {
        a["key"]: a
        for a in compute_exposure(
            inputs=[_units(), _margin()],
            currency="GBP",
            formula_key="k",
            formula_version=1,
            confidence_band=ConfidenceBand.MEDIUM,
        ).assumptions
    }

    assert records["units"]["kind"] == "observed"
    assert records["margin_minor"]["kind"] == "assumption"
    assert records["margin_minor"]["value"] == "200..300 (base 250)"


# --- the arithmetic ---------------------------------------------------------


def test_the_interval_is_the_product_of_the_inputs_three_ways() -> None:
    exposure = compute_exposure(
        inputs=[_units(), _margin()],
        currency="GBP",
        formula_key="stock_truth_exposure",
        formula_version=1,
        confidence_band=ConfidenceBand.MEDIUM,
    )

    assert exposure.low_minor == 42 * 200
    assert exposure.base_minor == 42 * 250
    assert exposure.high_minor == 42 * 300


def test_the_interval_is_the_widest_honest_one_not_a_statistical_combination() -> None:
    """Three modelled inputs each ±20% must compound, not cancel.

    The inputs are not independent samples; narrowing the range would rest on an
    assumption nobody has justified.
    """
    factors = [
        assumed(
            f"f{i}", f"factor {i}", low=Decimal(8), base=Decimal(10), high=Decimal(12), source="s"
        )
        for i in range(3)
    ]
    exposure = compute_exposure(
        inputs=factors,
        currency="GBP",
        formula_key="k",
        formula_version=1,
        confidence_band=ConfidenceBand.MEDIUM,
    )

    assert exposure.low_minor == 8 * 8 * 8
    assert exposure.base_minor == 1000
    assert exposure.high_minor == 12 * 12 * 12


def test_an_exposure_needs_at_least_one_input() -> None:
    with pytest.raises(ExposureError, match="at least one input"):
        compute_exposure(
            inputs=[],
            currency="GBP",
            formula_key="k",
            formula_version=1,
            confidence_band=ConfidenceBand.MEDIUM,
        )


def test_an_input_must_be_ordered() -> None:
    with pytest.raises(ValueError, match="low <= base <= high"):
        ExposureInput(
            key="k",
            statement="s",
            low=Decimal(10),
            base=Decimal(5),
            high=Decimal(20),
            kind=InputKind.ASSUMPTION,
            source="s",
        )


# --- money never touches a float --------------------------------------------


def test_money_never_passes_through_a_float() -> None:
    """`int(19.99 * 100)` is 1998. An exposure figure is exactly the kind of
    number somebody quotes back at you."""
    exposure = compute_exposure(
        inputs=[observed("price", "unit price", Decimal("1999"), "src")],
        currency="GBP",
        formula_key="k",
        formula_version=1,
        confidence_band=ConfidenceBand.HIGH,
    )
    assert exposure.base_minor == 1999

    scaled = compute_exposure(
        inputs=[
            observed("units", "units", Decimal(100), "src"),
            observed("price_minor", "price in pence", Decimal("19.99") * 100, "src"),
        ],
        currency="GBP",
        formula_key="k",
        formula_version=1,
        confidence_band=ConfidenceBand.HIGH,
    )
    assert scaled.base_minor == 199900


def test_rounding_is_half_up_not_bankers() -> None:
    """Python's round() is half-to-even: round(2.5) is 2. Money is not."""
    half = compute_exposure(
        inputs=[observed("v", "v", Decimal("2.5"), "src")],
        currency="GBP",
        formula_key="k",
        formula_version=1,
        confidence_band=ConfidenceBand.HIGH,
    )
    assert half.base_minor == 3

    also_half = compute_exposure(
        inputs=[observed("v", "v", Decimal("3.5"), "src")],
        currency="GBP",
        formula_key="k",
        formula_version=1,
        confidence_band=ConfidenceBand.HIGH,
    )
    assert also_half.base_minor == 4


def test_exposure_figures_are_integers() -> None:
    exposure = compute_exposure(
        inputs=[observed("v", "v", Decimal("1.4"), "src")],
        currency="GBP",
        formula_key="k",
        formula_version=1,
        confidence_band=ConfidenceBand.HIGH,
    )
    assert isinstance(exposure.base_minor, int)
    assert not isinstance(exposure.base_minor, bool)


# --- observability bounds the claim -----------------------------------------


def test_one_modelled_input_makes_the_whole_exposure_modelled() -> None:
    """There is no partially-observed money: the weakest input sets the
    character of the answer."""
    exposure = compute_exposure(
        inputs=[_units(), _margin()],
        currency="GBP",
        formula_key="k",
        formula_version=1,
        confidence_band=ConfidenceBand.MEDIUM,
    )

    assert exposure.is_modelled
    assert "modelled_exposure" in exposure.reason_codes


def test_an_entirely_observed_exposure_is_not_labelled_modelled() -> None:
    exposure = compute_exposure(
        inputs=[_units(), observed("price", "price", Decimal(100), "src")],
        currency="GBP",
        formula_key="k",
        formula_version=1,
        confidence_band=ConfidenceBand.HIGH,
    )

    assert not exposure.is_modelled
    assert "modelled_exposure" not in exposure.reason_codes


def test_a_governed_metric_input_is_modelled() -> None:
    """A distribution is not an observation of this gap's value."""
    metric_input = from_governed_metric(
        "basket_value",
        "Median basket value",
        p25=Decimal(1500),
        median=Decimal(2200),
        p75=Decimal(3100),
        metric_identity="basket_value@v2",
    )

    assert metric_input.is_modelled
    assert metric_input.source == "basket_value@v2"
    assert (metric_input.low, metric_input.base, metric_input.high) == (
        Decimal(1500),
        Decimal(2200),
        Decimal(3100),
    )


# --- a wide interval is a confidence statement ------------------------------


def test_a_wide_interval_forces_the_band_to_low() -> None:
    """An interval this wide is the model saying it does not know; a confident
    band beside it would contradict the arithmetic it sits next to."""
    exposure = compute_exposure(
        inputs=[assumed("f", "f", low=Decimal(1), base=Decimal(5), high=Decimal(100), source="s")],
        currency="GBP",
        formula_key="k",
        formula_version=1,
        confidence_band=ConfidenceBand.HIGH,
    )

    assert exposure.confidence_band is ConfidenceBand.LOW
    assert "wide_exposure_interval" in exposure.reason_codes


def test_a_narrow_interval_keeps_the_supplied_band() -> None:
    exposure = compute_exposure(
        inputs=[
            assumed("f", "f", low=Decimal(100), base=Decimal(120), high=Decimal(150), source="s")
        ],
        currency="GBP",
        formula_key="k",
        formula_version=1,
        confidence_band=ConfidenceBand.HIGH,
    )

    assert exposure.confidence_band is ConfidenceBand.HIGH
    assert "wide_exposure_interval" not in exposure.reason_codes


def test_a_zero_low_bound_does_not_divide_by_zero() -> None:
    exposure = compute_exposure(
        inputs=[assumed("f", "f", low=Decimal(0), base=Decimal(5), high=Decimal(100), source="s")],
        currency="GBP",
        formula_key="k",
        formula_version=1,
        confidence_band=ConfidenceBand.MEDIUM,
    )
    assert exposure.low_minor == 0
    assert exposure.confidence_band is ConfidenceBand.MEDIUM


def test_the_wide_interval_threshold_is_configurable_per_formula() -> None:
    inputs = [assumed("f", "f", low=Decimal(100), base=Decimal(200), high=Decimal(300), source="s")]
    tolerant = compute_exposure(
        inputs=inputs,
        currency="GBP",
        formula_key="k",
        formula_version=1,
        confidence_band=ConfidenceBand.HIGH,
        wide_interval_ratio=5.0,
    )
    strict = compute_exposure(
        inputs=inputs,
        currency="GBP",
        formula_key="k",
        formula_version=1,
        confidence_band=ConfidenceBand.HIGH,
        wide_interval_ratio=2.0,
    )

    assert tolerant.confidence_band is ConfidenceBand.HIGH
    assert strict.confidence_band is ConfidenceBand.LOW


# --- the copy ---------------------------------------------------------------


FORBIDDEN_WORDS = ("saving", "savings", "recover", "recovered", "profit", "guaranteed")


def test_describe_never_makes_a_savings_claim() -> None:
    """ "Potential savings" is a claim about money that would be recovered, which
    nothing here establishes."""
    exposure = compute_exposure(
        inputs=[_units(), _margin()],
        currency="GBP",
        formula_key="k",
        formula_version=1,
        confidence_band=ConfidenceBand.MEDIUM,
    )

    described = exposure.describe().lower()
    for word in FORBIDDEN_WORDS:
        assert word not in described, f"{word!r} appears in {described!r}"


def test_describe_states_the_interval_and_the_band() -> None:
    exposure = compute_exposure(
        inputs=[_units(), _margin()],
        currency="GBP",
        formula_key="k",
        formula_version=1,
        confidence_band=ConfidenceBand.MEDIUM,
    )

    described = exposure.describe()
    assert described.startswith("Estimated exposure GBP")
    assert "84.00" in described
    assert "126.00" in described
    assert "medium confidence" in described


def test_describe_never_shows_a_single_point_figure_alone() -> None:
    """A lone base figure reads as precision the model does not have."""
    exposure = compute_exposure(
        inputs=[_units(), _margin()],
        currency="GBP",
        formula_key="k",
        formula_version=1,
        confidence_band=ConfidenceBand.MEDIUM,
    )
    assert "\u2013" in exposure.describe(), "the range separator is the whole point"


# --- the gap mapping --------------------------------------------------------


def test_as_gap_fields_carries_all_four_required_parts() -> None:
    exposure = compute_exposure(
        inputs=[_units(), _margin()],
        currency="GBP",
        formula_key="k",
        formula_version=1,
        confidence_band=ConfidenceBand.MEDIUM,
    )

    fields = exposure.as_gap_fields()
    assert set(fields) == {
        "exposure_low",
        "exposure_base",
        "exposure_high",
        "currency",
        "assumptions",
        "confidence_band",
    }
    assert fields["assumptions"], "a gap may not carry money with no assumptions"
    assert fields["confidence_band"] == "medium"


def test_the_currency_is_normalised_to_upper_case() -> None:
    exposure = compute_exposure(
        inputs=[_units()],
        currency="gbp",
        formula_key="k",
        formula_version=1,
        confidence_band=ConfidenceBand.HIGH,
    )
    assert exposure.currency == "GBP"


def test_the_formula_version_is_recorded() -> None:
    """Changing an assumption must not silently change historical gap values;
    `formula_version` is what pins them."""
    exposure = compute_exposure(
        inputs=[_units(), _margin()],
        currency="GBP",
        formula_key="stock_truth_exposure",
        formula_version=3,
        confidence_band=ConfidenceBand.MEDIUM,
    )
    assert exposure.formula_key == "stock_truth_exposure"
    assert exposure.formula_version == 3


def test_an_exposure_is_immutable() -> None:
    exposure = compute_exposure(
        inputs=[_units()],
        currency="GBP",
        formula_key="k",
        formula_version=1,
        confidence_band=ConfidenceBand.HIGH,
    )
    with pytest.raises(FrozenInstanceError):
        exposure.base_minor = 999  # type: ignore[misc]
