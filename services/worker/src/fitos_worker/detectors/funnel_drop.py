"""Funnel drop.

Sessions to cart to order; install to activation to first purchase; trial to
purchase to return. The family is the same shape every time: ordered stages,
each a subset of the last, and a step where more people leave than should.

The design decisions that matter:

**It reports the worst *step*, not the worst total.** A funnel ending at 2%
conversion is not actionable; "84% of people who reached the basket did not
check out" is. Reporting the end-to-end number would be arithmetically true and
operationally useless, which is how a funnel chart becomes wallpaper.

**Stage counts must be non-increasing.** A stage larger than the one before it
is a join fan-out or a mis-mapped event, not a funnel. The detector refuses
rather than reporting a negative drop-off, because a negative drop-off renders
as a suspiciously good number and nobody investigates those.

**Thresholds are per step.** A 60% drop between "session" and "product view" is
normal; a 60% drop between "payment details" and "order" is a broken checkout.
One global threshold makes the detector either deaf at the top of the funnel or
deafening at the bottom.

**No exposure by default.** A drop-off is not money until somebody says what a
conversion is worth, and there is a config field for that rather than an
assumption.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    score_confidence,
)
from fitos_worker.detectors.exposure import Exposure, assumed, compute_exposure, observed


class FunnelStage(BaseModel):
    """One step, and the drop-off that is normal for it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    # Expected share surviving *into* this stage from the previous one. The
    # first stage has no predecessor and carries None.
    expected_survival: Decimal | None = None
    # Below this share surviving, the step is a finding. Per step, because a
    # 60% drop from session to product view is normal and the same drop from
    # payment details to order is a broken checkout.
    threshold_survival: Decimal | None = None

    @model_validator(mode="after")
    def _bounds_are_shares(self) -> FunnelStage:
        for name, value in (
            ("expected_survival", self.expected_survival),
            ("threshold_survival", self.threshold_survival),
        ):
            if value is not None and not (0 <= value <= 1):
                raise ValueError(f"{name} is {value}; a survival share is in 0..1")
        if (
            self.expected_survival is not None
            and self.threshold_survival is not None
            and self.threshold_survival > self.expected_survival
        ):
            raise ValueError(
                f"{self.key}: threshold_survival {self.threshold_survival} is above "
                f"expected {self.expected_survival}; the step would always fire"
            )
        return self


class FunnelDropConfig(DetectorConfig):
    gap_type: str = Field(min_length=1)
    canonical_entity: str = Field(min_length=1)
    funnel_name: str = Field(min_length=1)
    scope_dimension: str = "location_id"
    scope_type: ScopeType = ScopeType.LOCATION

    stages: list[FunnelStage] = Field(min_length=2)

    severity_high_shortfall: Decimal = Decimal("0.20")
    severity_critical_shortfall: Decimal = Decimal("0.40")

    # Opt-in, as everywhere else. A drop-off is not money until somebody says
    # what a conversion is worth.
    value_per_conversion_minor: Decimal | None = None
    exposure_currency: str = "GBP"
    exposure_formula_version: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _every_step_after_the_first_can_fire(self) -> FunnelDropConfig:
        first, *rest = self.stages
        if first.threshold_survival is not None:
            raise ValueError(
                f"{first.key} is the first stage and has no predecessor; "
                "it cannot have a threshold_survival"
            )
        missing = [s.key for s in rest if s.threshold_survival is None]
        if missing:
            # A stage with no threshold is a stage the detector silently never
            # checks, which looks identical to one that is always healthy.
            raise ValueError(
                f"these stages have no threshold_survival and would never fire: {missing}"
            )
        keys = [s.key for s in self.stages]
        if len(keys) != len(set(keys)):
            raise ValueError(f"duplicate stage keys: {keys}")
        return self


class FunnelDropDetector(Detector):
    """The step where more people leave than should.

    One reading per scope, carrying each stage's count in its dimensions keyed
    by stage key. Counts as dimensions rather than separate readings keeps a
    funnel atomic: half a funnel is not a funnel, and two readings could arrive
    from different windows.
    """

    key = "funnel_drop"
    config_model = FunnelDropConfig

    def __init__(self, config: FunnelDropConfig) -> None:
        super().__init__(config)
        self.config: FunnelDropConfig = config
        self.gap_type = config.gap_type

    def detect(
        self, readings: Sequence[MetricReading], context: DetectorContext
    ) -> list[GapCandidate]:
        candidates: list[GapCandidate] = []
        for reading in readings:
            candidate = self._candidate(reading, context)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    def _counts(self, reading: MetricReading) -> list[int] | None:
        config = self.config
        counts: list[int] = []
        for stage in config.stages:
            raw = reading.dimensions.get(stage.key)
            if raw is None:
                # An incomplete funnel is not a small funnel. Reporting a drop
                # to a stage that was never measured would invent one.
                return None
            counts.append(int(raw))

        for previous, current, stage in zip(
            counts[:-1], counts[1:], config.stages[1:], strict=True
        ):
            if current > previous:
                # A stage larger than the one before it is a join fan-out or a
                # mis-mapped event. A negative drop-off renders as a
                # suspiciously good number, and nobody investigates those.
                raise ValueError(
                    f"{stage.key} has {current} against {previous} in the previous stage; "
                    "funnel counts must be non-increasing"
                )
        return counts

    def _candidate(self, reading: MetricReading, context: DetectorContext) -> GapCandidate | None:
        config = self.config
        counts = self._counts(reading)
        if counts is None or counts[0] == 0:
            return None

        worst: tuple[FunnelStage, Decimal, Decimal, int, int] | None = None
        for index, stage in enumerate(config.stages[1:], start=1):
            entered, survived = counts[index - 1], counts[index]
            if entered == 0 or stage.threshold_survival is None:
                continue
            survival = Decimal(survived) / Decimal(entered)
            if survival >= stage.threshold_survival:
                continue
            expected = stage.expected_survival or stage.threshold_survival
            shortfall = expected - survival
            if worst is None or shortfall > worst[2]:
                worst = (stage, survival, shortfall, entered, survived)

        if worst is None:
            return None

        stage, survival, shortfall, entered, survived = worst
        scope_id = reading.dimension(config.scope_dimension)
        expected = stage.expected_survival or stage.threshold_survival or Decimal(0)
        lost = entered - survived
        confidence = self._score(entered)
        exposure = self._exposure(entered, survival, expected, confidence)

        return GapCandidate(
            gap_type=config.gap_type,
            pack_key=config.pack_key,
            scope_type=config.scope_type,
            scope_id=scope_id,
            # The step, not the end-to-end number. "2% overall conversion" is
            # true and unactionable; this names where to look.
            title=(
                f"{stage.label} step at {scope_id}: {survival:.0%} continue "
                f"(expected {expected:.0%})"
            ),
            summary=(
                f"{lost} of {entered} who reached {stage.label} in the {config.funnel_name} "
                f"funnel did not continue. That is {survival:.0%} against an expected "
                f"{expected:.0%}. This locates the step; it does not establish why."
            ),
            metric_key=reading.metric_key,
            metric_version=reading.metric_version,
            observed_value=survival,
            expected_value=expected,
            unit=Unit.RATIO,
            window=context.window,
            evidence=(
                EvidenceRef.from_reading(
                    reading,
                    canonical_entity=config.canonical_entity,
                    window=context.window,
                ),
            ),
            severity=self._severity(shortfall),
            confidence=confidence,
            exposure=exposure,
            reason_codes=("funnel_step_below_threshold", f"stage_{stage.key}"),
            correlation_keys=(f"metric:{reading.metric_identity}",),
        )

    def _score(self, entered: int) -> ConfidenceResult:
        return score_confidence(
            {
                Component.SAMPLE_SIZE: SampleSizeScore(
                    observations=entered, minimum=self.config.minimum_observations
                ).value,
                Component.DETECTOR_FIT: 1.0,
            }
        )

    def _exposure(
        self,
        entered: int,
        survival: Decimal,
        expected: Decimal,
        confidence: ConfidenceResult,
    ) -> Exposure | None:
        config = self.config
        if config.value_per_conversion_minor is None:
            return None
        missing = ((expected - survival) * Decimal(entered)).to_integral_value()
        if missing <= 0:
            return None

        return compute_exposure(
            inputs=[
                observed(
                    key="conversions_short",
                    statement=(
                        f"{missing} fewer continued than the expected {expected:.0%} of {entered}"
                    ),
                    value=missing,
                    source="funnel_counts",
                ),
                assumed(
                    key="value_per_conversion_minor",
                    statement="Value of one conversion at this step, set by the organisation",
                    low=config.value_per_conversion_minor,
                    base=config.value_per_conversion_minor,
                    high=config.value_per_conversion_minor,
                    source="organization_assumption",
                ),
            ],
            currency=config.exposure_currency,
            formula_key=f"{config.gap_type}_exposure",
            formula_version=config.exposure_formula_version,
            confidence_band=confidence.band,
        )

    def _severity(self, shortfall: Decimal) -> Severity:
        if shortfall >= self.config.severity_critical_shortfall:
            return Severity.CRITICAL
        if shortfall >= self.config.severity_high_shortfall:
            return Severity.HIGH
        return Severity.MEDIUM


__all__ = ["FunnelDropConfig", "FunnelDropDetector", "FunnelStage"]
