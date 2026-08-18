"""Ratio threshold — a governed ratio moves outside its expected band.

The general-purpose detector: conversion rate, completeness, on-time rate,
attach rate. It reads one governed ratio metric and fires when a scope sits
outside the configured band.

Two things it deliberately does not do:

**It does not claim a cause.** A conversion rate below band is a conversion rate
below band. The detector has one metric and one window; it has no basis for
saying why, and `direction` in the copy is a description of the movement rather
than an explanation of it.

**It does not compute exposure by default.** A ratio moving is not money until
somebody supplies the value of a unit of that ratio, and inventing one to make
the gap look important is exactly the failure the exposure rules exist to
prevent. `exposure_per_unit_minor` is opt-in per rule, and when it is absent the
gap carries no monetary figure at all — which is a legitimate, complete gap.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from enum import StrEnum

from pydantic import Field, model_validator

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
    ConfidenceResult,
    SampleSizeScore,
    freshness_score,
    score_confidence,
)
from fitos_worker.detectors.exposure import (
    Exposure,
    assumed,
    compute_exposure,
    observed,
)


class Direction(StrEnum):
    """Which way is bad.

    Explicit rather than inferred, because both directions are real: a
    conversion rate below band is a problem and a return rate above band is a
    problem, and a detector that guesses gets one of them backwards silently.
    """

    BELOW = "below"
    ABOVE = "above"
    EITHER = "either"


class RatioThresholdConfig(DetectorConfig):
    scope_dimension: str = "location_id"
    scope_type: ScopeType = ScopeType.LOCATION
    canonical_entity: str = "fact_order_line"
    gap_type: str = Field(min_length=1)
    title_template: str = "{metric_name} at {scope_id} is {direction} its expected band"
    metric_name: str = Field(min_length=1)

    expected_value: Decimal
    lower_bound: Decimal | None = None
    upper_bound: Decimal | None = None
    direction: Direction = Direction.EITHER

    # Distance past the bound, as a share of the bound, at which severity steps
    # up. Relative rather than absolute so one config works across metrics whose
    # natural scales differ by orders of magnitude.
    severity_high_excess: Decimal = Decimal("0.25")
    severity_critical_excess: Decimal = Decimal("0.50")

    # Opt-in. Absent means the gap carries no money, which is a complete gap.
    exposure_per_unit_minor: Decimal | None = None
    exposure_denominator_dimension: str | None = None
    exposure_currency: str = "GBP"
    exposure_formula_version: int = Field(default=1, ge=1)

    expected_source_latency_seconds: float = 86_400.0

    @model_validator(mode="after")
    def _bounds_match_direction(self) -> RatioThresholdConfig:
        if self.direction in (Direction.BELOW, Direction.EITHER) and self.lower_bound is None:
            raise ValueError(f"direction {self.direction} needs a lower_bound")
        if self.direction in (Direction.ABOVE, Direction.EITHER) and self.upper_bound is None:
            raise ValueError(f"direction {self.direction} needs an upper_bound")
        if (
            self.lower_bound is not None
            and self.upper_bound is not None
            and self.lower_bound > self.upper_bound
        ):
            raise ValueError(
                f"lower_bound {self.lower_bound} is above upper_bound {self.upper_bound}; "
                "no value can satisfy this band and the rule would fire on everything"
            )
        return self

    @model_validator(mode="after")
    def _exposure_is_complete_or_absent(self) -> RatioThresholdConfig:
        if self.exposure_per_unit_minor is not None and not self.exposure_denominator_dimension:
            # Half-configured exposure is the dangerous state: it produces a
            # figure from a denominator nobody chose.
            raise ValueError(
                "exposure_per_unit_minor needs exposure_denominator_dimension; "
                "a per-unit value with no unit count is not an exposure"
            )
        return self


class RatioThresholdDetector(Detector):
    """A governed ratio sits outside its configured band."""

    key = "ratio_threshold"
    gap_type = "ratio_out_of_band"
    config_model = RatioThresholdConfig

    def __init__(self, config: RatioThresholdConfig) -> None:
        super().__init__(config)
        self.config: RatioThresholdConfig = config
        self.gap_type = config.gap_type

    def detect(
        self, readings: Sequence[MetricReading], context: DetectorContext
    ) -> list[GapCandidate]:
        candidates = []
        for reading in readings:
            candidate = self._candidate(reading, context)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    def _breach(self, value: Decimal) -> tuple[str, Decimal] | None:
        """Which bound was crossed and by how much, relative to the bound."""
        config = self.config
        if (
            config.direction in (Direction.BELOW, Direction.EITHER)
            and config.lower_bound is not None
            and value < config.lower_bound
        ):
            excess = (
                (config.lower_bound - value) / config.lower_bound
                if config.lower_bound
                else (Decimal(0))
            )
            return "below", excess
        if (
            config.direction in (Direction.ABOVE, Direction.EITHER)
            and config.upper_bound is not None
            and value > config.upper_bound
        ):
            excess = (
                (value - config.upper_bound) / config.upper_bound
                if config.upper_bound
                else (Decimal(0))
            )
            return "above", excess
        return None

    def _candidate(self, reading: MetricReading, context: DetectorContext) -> GapCandidate | None:
        config = self.config
        if reading.value is None:
            # Null is "not measured", not "zero". A completeness metric reading
            # null for a source that sent nothing is the absence of data, and
            # scoring it as a 0% ratio would raise a gap about a number that was
            # never computed.
            return None

        breach = self._breach(reading.value)
        if breach is None:
            return None
        direction, excess = breach

        scope_id = reading.dimension(config.scope_dimension)
        observations = reading.denominator or 0
        freshness_seconds = self._freshness_seconds(reading, context)
        confidence = self._score(reading, observations, freshness_seconds)
        exposure = self._exposure(reading, observations, confidence)

        reason_codes: tuple[str, ...] = (f"ratio_{direction}_band",)
        if exposure is not None:
            reason_codes = (*reason_codes, *exposure.reason_codes)

        return GapCandidate(
            gap_type=config.gap_type,
            pack_key=config.pack_key,
            scope_type=config.scope_type,
            scope_id=scope_id,
            title=config.title_template.format(
                metric_name=config.metric_name, scope_id=scope_id, direction=direction
            ),
            summary=(
                f"{config.metric_name} at {scope_id} was {reading.value:.1%} over "
                f"{observations} observations, against an expected "
                f"{config.expected_value:.1%}. This describes the movement; it does not "
                f"establish its cause."
            ),
            metric_key=reading.metric_key,
            metric_version=reading.metric_version,
            observed_value=reading.value,
            expected_value=config.expected_value,
            unit=Unit.RATIO,
            window=context.window,
            evidence=(
                EvidenceRef.from_reading(
                    reading,
                    canonical_entity=config.canonical_entity,
                    window=context.window,
                ),
            ),
            severity=self._severity(excess),
            confidence=confidence,
            exposure=exposure,
            reason_codes=reason_codes,
            data_freshness_seconds=freshness_seconds,
            correlation_keys=(f"metric:{reading.metric_identity}",),
        )

    @staticmethod
    def _freshness_seconds(reading: MetricReading, context: DetectorContext) -> int | None:
        if reading.source_max_timestamp is None:
            return None
        return int((context.window.as_of - reading.source_max_timestamp).total_seconds())

    def _score(
        self, reading: MetricReading, observations: int, freshness_seconds: int | None
    ) -> ConfidenceResult:
        components = {
            Component.SAMPLE_SIZE: SampleSizeScore(
                observations=observations, minimum=self.config.minimum_observations
            ).value,
            Component.DETECTOR_FIT: 1.0,
        }
        if freshness_seconds is not None:
            components[Component.FRESHNESS] = freshness_score(
                age_seconds=float(freshness_seconds),
                expected_latency_seconds=self.config.expected_source_latency_seconds,
            )
        return score_confidence(components)

    def _exposure(
        self, reading: MetricReading, observations: int, confidence: ConfidenceResult
    ) -> Exposure | None:
        """None unless the rule declares what a unit of this ratio is worth.

        A ratio moving is not money. Inventing a per-unit value to make the gap
        look important is precisely what the exposure rules exist to prevent, and
        a gap with no monetary figure is complete.
        """
        config = self.config
        if config.exposure_per_unit_minor is None or reading.value is None:
            return None

        shortfall = abs(reading.value - config.expected_value) * Decimal(observations)
        if shortfall <= 0:
            return None

        return compute_exposure(
            inputs=[
                observed(
                    key="affected_units",
                    statement=(
                        f"{shortfall.to_integral_value()} units, from the difference between "
                        f"the observed and expected ratio over {observations} observations"
                    ),
                    value=shortfall.to_integral_value(),
                    source=reading.metric_identity,
                ),
                assumed(
                    key="value_per_unit_minor",
                    statement="Value of one unit of this ratio, set by the organisation",
                    low=config.exposure_per_unit_minor,
                    base=config.exposure_per_unit_minor,
                    high=config.exposure_per_unit_minor,
                    source="organization_assumption",
                ),
            ],
            currency=config.exposure_currency,
            formula_key=f"{config.gap_type}_exposure",
            formula_version=config.exposure_formula_version,
            confidence_band=confidence.band,
        )

    def _severity(self, excess: Decimal) -> Severity:
        if excess >= self.config.severity_critical_excess:
            return Severity.CRITICAL
        if excess >= self.config.severity_high_excess:
            return Severity.HIGH
        return Severity.MEDIUM
