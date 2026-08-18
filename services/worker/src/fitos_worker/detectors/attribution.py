"""Attribution comparison — low confidence by construction.

Campaign spend against an attributable outcome. The class exists partly to be
the honest one: docs/product-spec.md lists it as "baseline comparison, low
confidence by construction", and that phrase is the whole design.

A correlation between spend and outcome does not establish the link. No sample
size changes that, no amount of model sophistication changes it, and the only
thing that would is an experiment. So:

**The confidence band is capped at `medium`, always**, with reason code
`attribution_limited`. This is not a heuristic the detector applies when it feels
uncertain — it is passed to `score_confidence(is_attribution_based=True)`, which
applies the cap after every other calculation so nothing can outvote it.

**The declared method travels with the gap.** `attribution_method` is one of a
closed set — last touch, first touch, linear, position-based, or a declared
model — and it lands in the reason codes. An attributed number whose method is
not stated is a number nobody can argue with, which is the same as one nobody
should trust.

**The copy may not use causal language.** "Coincides with" and "is associated
with" are permitted; "caused", "drove" and "delivered" are not. Only a
`controlled_test` outcome may make a causal claim anywhere in this product, and
this detector is definitionally not one.

**Exposure is optional and modelled when present.** The spend is observed — it
is a real invoice — but what it produced is not, so any exposure here is an
interval with the attribution assumption recorded in it.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from enum import StrEnum

from pydantic import Field

from fitos_worker.detectors.base import (
    Detector,
    DetectorConfig,
    DetectorContext,
    EvidenceRef,
    GapCandidate,
    MetricReading,
    ScopeType,
    Severity,
    Unit,
)
from fitos_worker.detectors.confidence import (
    Component,
    ConfidenceBand,
    ConfidenceResult,
    SampleSizeScore,
    score_confidence,
)
from fitos_worker.detectors.exposure import Exposure, assumed, compute_exposure, observed


class AttributionMethod(StrEnum):
    """Closed set. An attributed number whose method is not stated is a number
    nobody can check."""

    LAST_TOUCH = "last_touch"
    FIRST_TOUCH = "first_touch"
    LINEAR = "linear"
    POSITION_BASED = "position_based"
    DECLARED_MODEL = "declared_model"


# Words that would turn an association into a claim this detector cannot make.
FORBIDDEN_CAUSAL_WORDS = (
    "caused",
    "drove",
    "delivered",
    "generated",
    "resulted in",
    "because of",
    "thanks to",
    "uplift",
)


class AttributionConfig(DetectorConfig):
    gap_type: str = Field(min_length=1)
    canonical_entity: str = Field(min_length=1)
    metric_name: str = Field(min_length=1)
    scope_dimension: str = "campaign_id"
    scope_type: ScopeType = ScopeType.CAMPAIGN

    # The method must be declared. There is no default: an attribution model
    # chosen by omission is the one thing worse than a contested one.
    attribution_method: AttributionMethod

    # Expected attributable outcome per unit of spend, and how far below it is
    # worth surfacing. Both are baselines the tenant sets, not universals.
    expected_ratio: Decimal
    threshold_ratio: Decimal
    severity_high_ratio: Decimal | None = None
    severity_critical_ratio: Decimal | None = None

    # Optional. Absent means the gap carries no money, which is complete.
    exposure_currency: str = "GBP"
    exposure_formula_version: int = Field(default=1, ge=1)
    # The share of the attributed outcome the tenant believes is genuinely
    # attributable. A band, never a point: the width is the honesty.
    attributable_share_low: Decimal | None = None
    attributable_share_base: Decimal | None = None
    attributable_share_high: Decimal | None = None


class AttributionDetector(Detector):
    """Campaign spend against an attributable outcome, under a declared method."""

    key = "attribution_comparison"
    gap_type = "attribution_below_baseline"
    config_model = AttributionConfig

    def __init__(self, config: AttributionConfig) -> None:
        super().__init__(config)
        self.config: AttributionConfig = config
        self.gap_type = config.gap_type

    def detect(
        self, readings: Sequence[MetricReading], context: DetectorContext
    ) -> list[GapCandidate]:
        config = self.config
        candidates: list[GapCandidate] = []

        for reading in readings:
            if reading.value is None:
                continue
            if reading.value >= config.threshold_ratio:
                continue

            scope_id = reading.dimension(config.scope_dimension)
            observations = reading.denominator or 0
            confidence = self._score(reading, observations)
            exposure = self._exposure(reading, observations, confidence)

            reason_codes: tuple[str, ...] = (
                "attribution_below_baseline",
                f"method_{config.attribution_method.value}",
                *confidence.reason_codes,
            )
            if exposure is not None:
                reason_codes = (*reason_codes, *exposure.reason_codes)

            candidates.append(
                GapCandidate(
                    gap_type=config.gap_type,
                    pack_key=config.pack_key,
                    scope_type=config.scope_type,
                    scope_id=scope_id,
                    title=(
                        f"{config.metric_name} for {scope_id} is below its baseline "
                        f"({reading.value:.2f} against {config.expected_ratio:.2f})"
                    ),
                    summary=self._summary(scope_id, reading.value, observations),
                    metric_key=reading.metric_key,
                    metric_version=reading.metric_version,
                    observed_value=reading.value,
                    expected_value=config.expected_ratio,
                    unit=Unit.RATIO,
                    window=context.window,
                    evidence=(
                        EvidenceRef.from_reading(
                            reading,
                            canonical_entity=config.canonical_entity,
                            window=context.window,
                        ),
                    ),
                    severity=self._severity(reading.value),
                    confidence=confidence,
                    exposure=exposure,
                    reason_codes=reason_codes,
                    correlation_keys=(f"metric:{reading.metric_identity}",),
                )
            )
        return candidates

    def _score(self, reading: MetricReading, observations: int) -> ConfidenceResult:
        """Capped at `medium` by construction, not by judgement.

        `is_attribution_based=True` makes `score_confidence` apply the cap after
        everything else, so a large sample and a fresh source cannot talk it
        upward. That is the difference between a rule and a preference.
        """
        return score_confidence(
            {
                Component.SAMPLE_SIZE: SampleSizeScore(
                    observations=observations, minimum=self.config.minimum_observations
                ).value,
                # Deliberately not 1.0. The detector fits the data it was given;
                # whether the data can answer the question is the point at issue.
                Component.DETECTOR_FIT: 0.6,
            },
            is_attribution_based=True,
        )

    def _exposure(
        self, reading: MetricReading, observations: int, confidence: ConfidenceResult
    ) -> Exposure | None:
        config = self.config
        if (
            config.attributable_share_low is None
            or config.attributable_share_base is None
            or config.attributable_share_high is None
            or reading.value is None
        ):
            return None

        shortfall = (config.expected_ratio - reading.value) * Decimal(observations)
        if shortfall <= 0:
            return None

        return compute_exposure(
            inputs=[
                observed(
                    key="attributed_shortfall",
                    statement=(
                        f"{shortfall.to_integral_value()} units below baseline over "
                        f"{observations} observations"
                    ),
                    value=shortfall.to_integral_value(),
                    source=reading.metric_identity,
                ),
                assumed(
                    key="attributable_share",
                    statement=(
                        f"Share genuinely attributable under the "
                        f"{config.attribution_method.value} model, set by the organisation"
                    ),
                    low=config.attributable_share_low,
                    base=config.attributable_share_base,
                    high=config.attributable_share_high,
                    source=f"organization_assumption:{config.attribution_method.value}",
                ),
            ],
            currency=config.exposure_currency,
            formula_key=f"{config.gap_type}_exposure",
            formula_version=config.exposure_formula_version,
            confidence_band=confidence.band,
        )

    def _summary(self, scope_id: str, observed_ratio: Decimal, observations: int) -> str:
        """Association, never causation.

        "Coincides with" is what the data supports. Every word in
        `FORBIDDEN_CAUSAL_WORDS` would claim more than a correlation under a
        chosen attribution model can carry, and a test asserts none appear.
        """
        return (
            f"{self.config.metric_name} for {scope_id} was {observed_ratio:.2f} over "
            f"{observations} observations, against a baseline of "
            f"{self.config.expected_ratio:.2f}. This coincides with the spend in this "
            f"window under the {self.config.attribution_method.value} model; the model "
            f"assigns credit, it does not establish that the spend produced the outcome."
        )

    def _severity(self, ratio: Decimal) -> Severity:
        config = self.config
        if config.severity_critical_ratio is not None and ratio <= config.severity_critical_ratio:
            return Severity.CRITICAL
        if config.severity_high_ratio is not None and ratio <= config.severity_high_ratio:
            return Severity.HIGH
        # Never critical by default. A campaign underperforming its baseline
        # under a contested model is not an emergency, and ranking it as one
        # crowds out findings that are.
        return Severity.MEDIUM


__all__ = [
    "FORBIDDEN_CAUSAL_WORDS",
    "AttributionConfig",
    "AttributionDetector",
    "AttributionMethod",
    "ConfidenceBand",
]
