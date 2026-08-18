"""Source mismatch — the Stock Truth Gap.

Two systems claim to describe the same physical thing and disagree. The retail
instance is the one the vertical slice is built around: the inventory system
says a location holds N units of a variant, somebody counted it, and the two
numbers differ.

The detector's job is deciding when a disagreement is a *finding* rather than
noise, and the interesting decisions are all refusals:

**Below the sample minimum it says nothing.** Two counts at a location, one of
which disagreed, is a 50% discrepancy rate and means nothing. "We do not have
enough data to say" and "we looked and it is fine" are different answers, and
raising a low-confidence gap conflates them. The refusal happens in
`Detector.sufficient`, so every detector refuses identically.

**It compares against the metric's expected value, not against zero.** Some
discrepancy is normal in every retail estate; a detector anchored at zero fires
on every location forever and is muted within a week.

**It never states a cause.** The title says the two sources disagree. It does
not say shrinkage, miscount or theft — the metric establishes a disagreement and
nothing else. `recommended_actions` proposes an investigation, which is a
suggestion about what to do next rather than a claim about what happened.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

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
    ConfidenceResult,
    SampleSizeScore,
    freshness_score,
    score_confidence,
)
from fitos_worker.detectors.exposure import (
    Exposure,
    ExposureInput,
    assumed,
    compute_exposure,
    observed,
)


class SourceMismatchConfig(DetectorConfig):
    """Thresholds for one source-mismatch rule.

    Every value here reaches the gap through `rule_version`, so a gap raised
    under a 5% threshold stays explicable after somebody moves the threshold
    to 8%.
    """

    scope_dimension: str = "location_id"
    scope_type: ScopeType = ScopeType.LOCATION
    canonical_entity: str = "fact_stock_count"

    # The rate a healthy estate runs at. Not zero: some discrepancy is normal
    # everywhere, and a detector anchored at zero fires on every location.
    expected_rate: Decimal = Decimal("0.02")
    # How far above expected before it is worth somebody's morning.
    threshold_rate: Decimal = Decimal("0.05")

    severity_high_rate: Decimal = Decimal("0.15")
    severity_critical_rate: Decimal = Decimal("0.30")

    # Exposure inputs. The margin band is a tenant assumption and is recorded as
    # one on every gap; changing it is an audited admin action that does not
    # retroactively alter existing gaps, because `formula_version` pins them.
    exposure_currency: str = "GBP"
    exposure_formula_version: int = Field(default=1, ge=1)
    unit_margin_minor_low: Decimal = Decimal("150")
    unit_margin_minor_base: Decimal = Decimal("220")
    unit_margin_minor_high: Decimal = Decimal("310")

    expected_source_latency_seconds: float = 86_400.0


class SourceMismatchDetector(Detector):
    """Two sources disagree about the same physical quantity."""

    key = "source_mismatch"
    gap_type = "stock_truth_mismatch"
    config_model = SourceMismatchConfig

    def __init__(self, config: SourceMismatchConfig) -> None:
        super().__init__(config)
        self.config: SourceMismatchConfig = config

    def detect(
        self, readings: Sequence[MetricReading], context: DetectorContext
    ) -> list[GapCandidate]:
        candidates = []
        for reading in readings:
            candidate = self._candidate(reading, context)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    def _candidate(self, reading: MetricReading, context: DetectorContext) -> GapCandidate | None:
        config = self.config

        if reading.value is None:
            # A null rate means an absent denominator, not a zero rate. Treating
            # it as zero would report every location with no counts as perfectly
            # accurate, which is the most confident possible way to be wrong.
            return None
        if reading.value <= config.threshold_rate:
            return None

        scope_id = reading.dimension(config.scope_dimension)
        observations = reading.denominator or 0
        freshness_seconds = self._freshness_seconds(reading, context)

        confidence = self._score(reading, observations, freshness_seconds)
        exposure = self._exposure(reading, observations, confidence)

        return GapCandidate(
            gap_type=self.gap_type,
            pack_key=config.pack_key,
            scope_type=config.scope_type,
            scope_id=scope_id,
            title=self._title(scope_id, reading.value),
            summary=self._summary(reading.value, observations),
            metric_key=reading.metric_key,
            metric_version=reading.metric_version,
            observed_value=reading.value,
            expected_value=config.expected_rate,
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
            reason_codes=("source_disagreement", *exposure.reason_codes),
            recommended_actions=(
                {
                    "key": "recount_location",
                    "title": "Recount the affected variants",
                    # An investigation, not a diagnosis. The metric establishes a
                    # disagreement; it does not establish shrinkage, miscount or
                    # theft, and the copy must not imply one.
                    "rationale": (
                        "Confirms whether the disagreement is in the count or in the "
                        "inventory record before anything is adjusted."
                    ),
                    "playbook_id": "retail.stock_truth.recount",
                },
            ),
            data_freshness_seconds=freshness_seconds,
            correlation_keys=(f"metric:{reading.metric_identity}",),
        )

    # -- scoring -----------------------------------------------------------

    @staticmethod
    def _freshness_seconds(reading: MetricReading, context: DetectorContext) -> int | None:
        if reading.source_max_timestamp is None:
            return None
        return int((context.window.as_of - reading.source_max_timestamp).total_seconds())

    def _score(
        self, reading: MetricReading, observations: int, freshness_seconds: int | None
    ) -> ConfidenceResult:
        assert reading.value is not None  # noqa: S101 - guarded by the caller
        components = {
            Component.SAMPLE_SIZE: SampleSizeScore(
                observations=observations, minimum=self.config.minimum_observations
            ).value,
            # For a comparison detector, "fit" means the comparison was possible:
            # both sources produced a value for this scope in this window.
            Component.DETECTOR_FIT: 1.0,
            # The agreement rate is the complement of the discrepancy rate. It is
            # a component rather than the whole score because two sources
            # agreeing on stale, incomplete data is not confidence.
            Component.SOURCE_AGREEMENT: float(max(Decimal(0), Decimal(1) - reading.value)),
        }
        if freshness_seconds is not None:
            components[Component.FRESHNESS] = freshness_score(
                age_seconds=float(freshness_seconds),
                expected_latency_seconds=self.config.expected_source_latency_seconds,
            )
        # Identity match and metric stability are not measured by this detector,
        # so they are omitted rather than guessed. `score_confidence` drops them
        # and renormalises, and the gap records which were dropped.
        return score_confidence(components)

    # -- exposure ----------------------------------------------------------

    def _exposure(
        self, reading: MetricReading, observations: int, confidence: ConfidenceResult
    ) -> Exposure:
        """Discrepant checks times a margin band.

        The count of discrepant checks is observed. The margin is an assumption,
        so the whole figure is modelled and says so. There is no attempt to
        model *which direction* the discrepancy runs: a unit the system thinks it
        has and does not is a lost sale, a unit it has and does not know about is
        tied-up capital, and both are exposure without either being a loss.
        """
        assert reading.value is not None  # noqa: S101 - guarded by the caller
        discrepant = (reading.value * Decimal(observations)).to_integral_value()
        config = self.config

        inputs: list[ExposureInput] = [
            observed(
                key="discrepant_checks",
                statement=(
                    f"{discrepant} of {observations} stock checks disagreed with the record"
                ),
                value=discrepant,
                source=reading.metric_identity,
            ),
            assumed(
                key="unit_margin_minor",
                statement="Contribution margin per unit, set by the organisation",
                low=config.unit_margin_minor_low,
                base=config.unit_margin_minor_base,
                high=config.unit_margin_minor_high,
                source="organization_assumption",
            ),
        ]
        return compute_exposure(
            inputs=inputs,
            currency=config.exposure_currency,
            formula_key="stock_truth_exposure",
            formula_version=config.exposure_formula_version,
            confidence_band=confidence.band,
        )

    # -- copy --------------------------------------------------------------

    @staticmethod
    def _title(scope_id: str, rate: Decimal) -> str:
        return f"Stock records and counts disagree at {scope_id} ({rate:.1%} of checks)"

    @staticmethod
    def _summary(rate: Decimal, observations: int) -> str:
        return (
            f"{rate:.1%} of {observations} stock checks in this window found a quantity "
            f"different from the inventory record. The two sources disagree; which one is "
            f"right is not established by this metric."
        )

    def _severity(self, rate: Decimal) -> Severity:
        if rate >= self.config.severity_critical_rate:
            return Severity.CRITICAL
        if rate >= self.config.severity_high_rate:
            return Severity.HIGH
        return Severity.MEDIUM
