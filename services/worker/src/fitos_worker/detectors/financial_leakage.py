"""Financial leakage — margin trend against revenue trend.

Revenue rising while margin falls is the family this detects. It is the one
place in the system where the detector's own output is money rather than a
ratio that money is later attached to, and that changes what it has to prove.

**Every component is observed, so the exposure is observed too.** Revenue,
cost of goods, returns and handling are all real ledger figures. That makes
this the only detector whose exposure can be `is_modelled = False` — and it is
only true when every input genuinely is observed, which the code checks rather
than assumes. A single modelled input makes the whole figure modelled, and the
constructor enforces that.

**A margin fall alone is not leakage.** Margin falling *while revenue rises* is
the finding: selling more at a worse rate. Margin falling while revenue falls
is a demand problem that a margin detector would misattribute, and margin
falling on flat revenue is a cost problem. The detector distinguishes them and
says which, in reason codes rather than in prose alone.

**It never says why the margin moved.** Discounting, mix shift, supplier
increase and returns all look identical in a margin number. The gap names the
components that moved, which is a decomposition — not an explanation.

**Currency is not optional and is never mixed.** Summing minor units across
currencies is meaningless, so a reading without a currency is refused rather
than assumed to be the organisation's default.
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
    ConfidenceResult,
    SampleSizeScore,
    score_confidence,
)
from fitos_worker.detectors.exposure import Exposure, compute_exposure, observed


class LeakageShape(StrEnum):
    """Which way the two trends moved. The distinction is the finding."""

    # Selling more at a worse rate — the classic leak.
    REVENUE_UP_MARGIN_DOWN = "revenue_up_margin_down"
    # Costs moved without volume moving.
    REVENUE_FLAT_MARGIN_DOWN = "revenue_flat_margin_down"
    # A demand problem a margin detector would misattribute.
    REVENUE_DOWN_MARGIN_DOWN = "revenue_down_margin_down"


class FinancialLeakageConfig(DetectorConfig):
    gap_type: str = Field(min_length=1)
    canonical_entity: str = Field(min_length=1)
    scope_dimension: str = "product_variant_id"
    scope_type: ScopeType = ScopeType.PRODUCT_VARIANT

    # Margin rate points lost against the prior period before it is a finding.
    threshold_margin_drop: Decimal = Decimal("0.02")
    severity_high_margin_drop: Decimal = Decimal("0.05")
    severity_critical_margin_drop: Decimal = Decimal("0.10")

    # Revenue movement below this is "flat". Without a band, ordinary noise
    # reclassifies the shape from one period to the next and the reason codes
    # become useless.
    revenue_flat_band: Decimal = Decimal("0.02")

    # Which shapes this rule raises. Defaults to the leak proper: a
    # revenue-down gap belongs to a demand detector, and raising it here would
    # put a margin explanation on a volume problem.
    shapes: list[LeakageShape] = Field(
        default_factory=lambda: [
            LeakageShape.REVENUE_UP_MARGIN_DOWN,
            LeakageShape.REVENUE_FLAT_MARGIN_DOWN,
        ],
        min_length=1,
    )

    exposure_formula_version: int = Field(default=1, ge=1)


class FinancialLeakageDetector(Detector):
    """Margin rate falling against the prior period, with the revenue shape.

    Readings carry the ledger figures in their dimensions, all in integer minor
    units: `revenue_minor`, `prior_revenue_minor`, `margin_rate`,
    `prior_margin_rate`, and `currency`.
    """

    key = "financial_leakage"
    config_model = FinancialLeakageConfig

    REQUIRED_DIMENSIONS = (
        "revenue_minor",
        "prior_revenue_minor",
        "margin_rate",
        "prior_margin_rate",
        "currency",
    )

    def __init__(self, config: FinancialLeakageConfig) -> None:
        super().__init__(config)
        self.config: FinancialLeakageConfig = config
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

    def _candidate(self, reading: MetricReading, context: DetectorContext) -> GapCandidate | None:
        config = self.config
        missing = [d for d in self.REQUIRED_DIMENSIONS if d not in reading.dimensions]
        if missing:
            # A partial ledger reading is not a small one. Computing a margin
            # movement from three of five figures would produce a number that
            # looks exactly like a real one.
            raise ValueError(
                f"financial leakage needs {list(self.REQUIRED_DIMENSIONS)}; missing {missing}"
            )

        currency = reading.dimension("currency")
        if len(currency) != 3 or not currency.isalpha():
            # Never assume the organisation default. Summing minor units across
            # currencies is meaningless, and a guessed currency is how that
            # happens without anybody choosing it.
            raise ValueError(f"{currency!r} is not an ISO 4217 code")

        margin = Decimal(reading.dimension("margin_rate"))
        prior_margin = Decimal(reading.dimension("prior_margin_rate"))
        drop = prior_margin - margin
        if drop < config.threshold_margin_drop:
            return None

        revenue = Decimal(reading.dimension("revenue_minor"))
        prior_revenue = Decimal(reading.dimension("prior_revenue_minor"))
        shape = self._shape(revenue, prior_revenue)
        if shape not in config.shapes:
            return None

        scope_id = reading.dimension(config.scope_dimension)
        confidence = self._score(reading)
        exposure = self._exposure(revenue, drop, currency, confidence)

        return GapCandidate(
            gap_type=config.gap_type,
            pack_key=config.pack_key,
            scope_type=config.scope_type,
            scope_id=scope_id,
            title=(
                f"Margin at {scope_id} fell {drop:.1%} against the prior period "
                f"({self._shape_phrase(shape)})"
            ),
            summary=(
                f"Margin rate at {scope_id} was {margin:.1%} against {prior_margin:.1%} in the "
                f"prior period, {self._shape_phrase(shape)}. The figures name what moved; "
                f"discounting, mix shift, supplier cost and returns are indistinguishable in "
                f"a margin rate and none of them is established here."
            ),
            metric_key=reading.metric_key,
            metric_version=reading.metric_version,
            observed_value=margin,
            expected_value=prior_margin,
            unit=Unit.RATIO,
            window=context.window,
            evidence=(
                EvidenceRef.from_reading(
                    reading,
                    canonical_entity=config.canonical_entity,
                    window=context.window,
                    sensitivity="confidential",
                ),
            ),
            severity=self._severity(drop),
            confidence=confidence,
            exposure=exposure,
            reason_codes=("margin_below_prior_period", shape.value),
            correlation_keys=(f"metric:{reading.metric_identity}",),
        )

    def _shape(self, revenue: Decimal, prior_revenue: Decimal) -> LeakageShape:
        if prior_revenue <= 0:
            # No prior revenue means no trend. Treated as flat rather than as
            # infinite growth, which is what a naive ratio would produce.
            return LeakageShape.REVENUE_FLAT_MARGIN_DOWN
        movement = (revenue - prior_revenue) / prior_revenue
        if movement > self.config.revenue_flat_band:
            return LeakageShape.REVENUE_UP_MARGIN_DOWN
        if movement < -self.config.revenue_flat_band:
            return LeakageShape.REVENUE_DOWN_MARGIN_DOWN
        return LeakageShape.REVENUE_FLAT_MARGIN_DOWN

    @staticmethod
    def _shape_phrase(shape: LeakageShape) -> str:
        return {
            LeakageShape.REVENUE_UP_MARGIN_DOWN: "while revenue rose",
            LeakageShape.REVENUE_FLAT_MARGIN_DOWN: "on broadly flat revenue",
            LeakageShape.REVENUE_DOWN_MARGIN_DOWN: "while revenue also fell",
        }[shape]

    def _score(self, reading: MetricReading) -> ConfidenceResult:
        """High by construction, and legitimately so.

        Unlike attribution, this is arithmetic over ledger figures: the margin
        rate either fell or it did not. What the detector does *not* claim is
        why, and that restraint lives in the copy rather than in a lowered
        score — de-confidencing an observation to signal caution about its
        interpretation would misreport the observation.
        """
        return score_confidence(
            {
                Component.SAMPLE_SIZE: SampleSizeScore(
                    observations=reading.denominator or 0,
                    minimum=self.config.minimum_observations,
                ).value,
                Component.DETECTOR_FIT: 1.0,
                Component.COMPLETENESS: 1.0,
            }
        )

    def _exposure(
        self, revenue: Decimal, drop: Decimal, currency: str, confidence: ConfidenceResult
    ) -> Exposure:
        """Revenue times the margin points lost. Both observed.

        The only exposure in the system that is not modelled — and it is marked
        so only because both inputs are real ledger figures. `observed()` is
        what makes that claim, and `compute_exposure` derives `is_modelled`
        from the inputs rather than taking it on trust.
        """
        return compute_exposure(
            inputs=[
                observed(
                    key="revenue_minor",
                    statement="Revenue in the window, from the ledger",
                    value=revenue,
                    source="fact_financial_line",
                ),
                observed(
                    key="margin_points_lost",
                    statement=f"Margin rate fell {drop} against the prior period",
                    value=drop,
                    source="fact_financial_line",
                ),
            ],
            currency=currency,
            formula_key=f"{self.config.gap_type}_exposure",
            formula_version=self.config.exposure_formula_version,
            confidence_band=confidence.band,
        )

    def _severity(self, drop: Decimal) -> Severity:
        if drop >= self.config.severity_critical_margin_drop:
            return Severity.CRITICAL
        if drop >= self.config.severity_high_margin_drop:
            return Severity.HIGH
        return Severity.MEDIUM


__all__ = [
    "FinancialLeakageConfig",
    "FinancialLeakageDetector",
    "LeakageShape",
]
