"""Tests for the confidence model.

Each test names the way a confidence score becomes a lie, and asserts the
module refuses it. The negative cases matter more than the positive ones: a
scoring function that always returns something plausible is indistinguishable
from one that works, which is the failure CLAUDE.md calls out by name.
"""

from __future__ import annotations

import pytest
from fitos_worker.detectors.confidence import (
    BAND_HIGH_FLOOR,
    CAP_TO_LOW_BELOW,
    CAP_TO_MEDIUM_BELOW,
    DEFAULT_WEIGHTS,
    Component,
    ConfidenceBand,
    SampleSizeScore,
    freshness_score,
    score_confidence,
)


def _all_components(value: float) -> dict[Component, float]:
    return dict.fromkeys(DEFAULT_WEIGHTS, value)


def test_default_weights_sum_to_one() -> None:
    """If they do not, the unrenormalised path is silently wrong."""
    assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)


def test_every_component_has_a_weight() -> None:
    assert set(DEFAULT_WEIGHTS) == set(Component)


def test_all_strong_components_score_high() -> None:
    result = score_confidence(_all_components(0.9))
    assert result.score == pytest.approx(0.9)
    assert result.band is ConfidenceBand.HIGH
    assert result.dropped == ()
    assert result.caps_applied == ()


def test_all_weak_components_score_low() -> None:
    result = score_confidence(_all_components(0.05))
    assert result.band is ConfidenceBand.LOW


# --- dropping and renormalisation -------------------------------------------


def test_absent_components_are_dropped_not_assumed() -> None:
    """The score must not move when a component is simply not measured.

    Treating an inapplicable component as 0 punishes a detector for a
    measurement that was never relevant; treating it as 1 rewards it. Dropping
    and renormalising is the only option that says nothing either way.
    """
    supplied = {Component.SAMPLE_SIZE: 0.8, Component.COMPLETENESS: 0.8}
    result = score_confidence(supplied)

    assert result.score == pytest.approx(0.8)
    assert result.dropped == (
        "detector_fit",
        "freshness",
        "identity_match",
        "metric_stability",
        "source_agreement",
    )


def test_renormalised_weights_sum_to_one() -> None:
    result = score_confidence(
        {Component.SAMPLE_SIZE: 0.8, Component.COMPLETENESS: 0.4, Component.FRESHNESS: 0.6}
    )
    assert sum(result.weights.values()) == pytest.approx(1.0, abs=1e-3)


def test_renormalisation_preserves_relative_weight() -> None:
    """sample_size (0.20) must still outweigh freshness (0.15) after dropping."""
    result = score_confidence({Component.SAMPLE_SIZE: 1.0, Component.FRESHNESS: 1.0})

    assert result.weights["sample_size"] == pytest.approx(0.20 / 0.35, abs=1e-3)
    assert result.weights["freshness"] == pytest.approx(0.15 / 0.35, abs=1e-3)
    assert result.weights["sample_size"] > result.weights["freshness"]


def test_dropping_does_not_deflate_the_score() -> None:
    """The regression this guards: renormalisation quietly removed.

    Without renormalising, a two-component score of 0.9 each would come out at
    0.9 * 0.40 = 0.36 and land in the LOW band, which reads as "we are unsure"
    when the truth is "the two things we measured were both excellent".
    """
    partial = score_confidence({Component.SAMPLE_SIZE: 0.9, Component.COMPLETENESS: 0.9})
    assert partial.score > BAND_HIGH_FLOOR
    assert partial.band is ConfidenceBand.HIGH


def test_dropped_set_is_recorded_for_audit() -> None:
    result = score_confidence({Component.DETECTOR_FIT: 0.5})
    assert "sample_size" in result.dropped
    assert "detector_fit" not in result.dropped


# --- the weak-component cap -------------------------------------------------


def test_one_weak_component_caps_the_band_at_medium() -> None:
    """Six strong components must not drown one bad one."""
    components = _all_components(1.0)
    components[Component.COMPLETENESS] = CAP_TO_MEDIUM_BELOW - 0.01

    result = score_confidence(components)

    assert result.score > BAND_HIGH_FLOOR, "the weighted mean alone would say HIGH"
    assert result.band is ConfidenceBand.MEDIUM
    assert result.caps_applied == (f"component below {CAP_TO_MEDIUM_BELOW}",)


def test_one_disqualifying_component_caps_the_band_at_low() -> None:
    components = _all_components(1.0)
    components[Component.COMPLETENESS] = CAP_TO_LOW_BELOW - 0.01

    result = score_confidence(components)

    assert result.score > BAND_HIGH_FLOOR
    assert result.band is ConfidenceBand.LOW
    assert result.caps_applied == (f"component below {CAP_TO_LOW_BELOW}",)


def test_a_component_exactly_at_the_threshold_does_not_cap() -> None:
    """The boundary is `<`, not `<=`. A detector declaring a minimum of 0.2 and
    hitting exactly 0.2 has met it."""
    components = _all_components(1.0)
    components[Component.COMPLETENESS] = CAP_TO_MEDIUM_BELOW

    result = score_confidence(components)

    assert result.band is ConfidenceBand.HIGH
    assert result.caps_applied == ()


def test_the_cap_only_lowers_never_raises() -> None:
    """A cap is a ceiling. A LOW score with a `medium` ceiling stays LOW."""
    components = {Component.SAMPLE_SIZE: 0.1, Component.COMPLETENESS: 0.15}
    result = score_confidence(components)

    assert result.score < 0.4
    assert result.band is ConfidenceBand.LOW


# --- the attribution rule ---------------------------------------------------


def test_attribution_based_gaps_cap_at_medium() -> None:
    result = score_confidence(_all_components(1.0), is_attribution_based=True)

    assert result.score == pytest.approx(1.0)
    assert result.band is ConfidenceBand.MEDIUM
    assert "attribution_limited" in result.reason_codes


def test_attribution_cannot_be_outvoted_by_perfect_components() -> None:
    """A correlation between spend and outcome does not establish the link, and
    no sample size changes that. This is the hard rule from gap-model.md §4."""
    for value in (0.7, 0.85, 0.95, 1.0):
        result = score_confidence(_all_components(value), is_attribution_based=True)
        assert result.band is not ConfidenceBand.HIGH


def test_attribution_does_not_raise_a_low_band() -> None:
    """It is a ceiling, not an assignment."""
    components = _all_components(0.05)
    result = score_confidence(components, is_attribution_based=True)

    assert result.band is ConfidenceBand.LOW
    assert "attribution_limited" in result.reason_codes


def test_non_attribution_gaps_carry_no_attribution_reason_code() -> None:
    result = score_confidence(_all_components(0.9))
    assert "attribution_limited" not in result.reason_codes


# --- the exposure interval rule ---------------------------------------------


def test_a_wide_exposure_interval_caps_the_band_at_low() -> None:
    result = score_confidence(_all_components(1.0), exposure_low=100, exposure_high=1000)

    assert result.band is ConfidenceBand.LOW
    assert "wide_exposure_interval" in result.reason_codes


def test_a_narrow_exposure_interval_does_not_cap() -> None:
    result = score_confidence(_all_components(1.0), exposure_low=100, exposure_high=200)

    assert result.band is ConfidenceBand.HIGH
    assert result.reason_codes == ()


def test_a_zero_low_exposure_does_not_divide_by_zero() -> None:
    result = score_confidence(_all_components(1.0), exposure_low=0, exposure_high=5000)
    assert result.band is ConfidenceBand.HIGH


def test_exposure_bounds_are_ignored_unless_both_are_given() -> None:
    assert score_confidence(_all_components(1.0), exposure_low=1).reason_codes == ()
    assert score_confidence(_all_components(1.0), exposure_high=99999).reason_codes == ()


# --- refusals ---------------------------------------------------------------


def test_no_components_is_a_refusal_not_a_default() -> None:
    """A gap with no measurable confidence must not be raised at all."""
    with pytest.raises(ValueError, match="at least one component"):
        score_confidence({})


@pytest.mark.parametrize("value", [-0.01, 1.01, 42.0])
def test_out_of_range_component_scores_are_rejected(value: float) -> None:
    with pytest.raises(ValueError, match=r"0\.\.1"):
        score_confidence({Component.SAMPLE_SIZE: value})


def test_a_component_with_no_weight_is_rejected() -> None:
    with pytest.raises(ValueError, match="no supplied component has a weight"):
        score_confidence({Component.SAMPLE_SIZE: 0.9}, weights={Component.COMPLETENESS: 1.0})


def test_custom_weights_are_honoured() -> None:
    result = score_confidence(
        {Component.SAMPLE_SIZE: 0.0, Component.COMPLETENESS: 1.0},
        weights={Component.SAMPLE_SIZE: 0.9, Component.COMPLETENESS: 0.1},
    )
    assert result.score == pytest.approx(0.1)


# --- sample size ------------------------------------------------------------


def test_sample_size_below_the_minimum_is_insufficient() -> None:
    """Where denominator_min_30 is actually enforced: as a refusal to make a
    claim, not as a dbt build failure."""
    assert not SampleSizeScore(observations=29, minimum=30).is_sufficient
    assert SampleSizeScore(observations=30, minimum=30).is_sufficient


def test_sample_size_score_is_linear_then_flat() -> None:
    assert SampleSizeScore(observations=15, minimum=30).value == pytest.approx(0.5)
    assert SampleSizeScore(observations=30, minimum=30).value == pytest.approx(1.0)
    assert SampleSizeScore(observations=400, minimum=30).value == pytest.approx(1.0)


def test_a_huge_sample_cannot_paper_over_a_weak_component() -> None:
    """The flat ceiling is what makes the weak-component cap survivable."""
    components = _all_components(1.0)
    components[Component.SAMPLE_SIZE] = SampleSizeScore(400, 30).value
    components[Component.COMPLETENESS] = 0.05

    assert score_confidence(components).band is ConfidenceBand.LOW


def test_no_declared_minimum_scores_one() -> None:
    assert SampleSizeScore(observations=0, minimum=0).value == 1.0
    assert SampleSizeScore(observations=0, minimum=0).is_sufficient


# --- freshness --------------------------------------------------------------


def test_freshness_is_one_inside_the_expected_latency() -> None:
    assert freshness_score(age_seconds=100, expected_latency_seconds=3600) == 1.0
    assert freshness_score(age_seconds=3600, expected_latency_seconds=3600) == 1.0


def test_freshness_decays_proportionally_when_late() -> None:
    assert freshness_score(7200, 3600) == pytest.approx(0.5)
    assert freshness_score(36000, 3600) == pytest.approx(0.1)


def test_freshness_never_reaches_zero() -> None:
    """ "Very stale" and "absent" are different conditions, and the second is a
    data-quality gap in its own right rather than a weak component."""
    assert freshness_score(10**9, 3600) > 0.0


def test_no_declared_cadence_scores_one() -> None:
    assert freshness_score(10**9, 0) == 1.0


# --- the result is explainable ----------------------------------------------


def test_the_result_carries_everything_needed_to_explain_it() -> None:
    result = score_confidence(
        {Component.SAMPLE_SIZE: 0.8, Component.COMPLETENESS: 0.15},
        is_attribution_based=True,
    )

    assert result.components == {"completeness": 0.15, "sample_size": 0.8}
    assert set(result.weights) == {"completeness", "sample_size"}
    assert result.caps_applied  # both the weak component and the attribution rule
    assert result.reason_codes == ("attribution_limited",)


def test_components_and_weights_are_stable_ordered() -> None:
    """Evidence is compared across runs; dict ordering must not make two
    identical scores look different."""
    first = score_confidence({Component.FRESHNESS: 0.5, Component.SAMPLE_SIZE: 0.5})
    second = score_confidence({Component.SAMPLE_SIZE: 0.5, Component.FRESHNESS: 0.5})

    assert list(first.components) == list(second.components)
    assert first == second
