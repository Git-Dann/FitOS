"""Peer and baseline comparison.

A scope is compared against its own past or against its peers. Footfall-to-
conversion is the family this was built for: a store converting at 18% is
meaningless until you know whether it converted at 24% last month, or whether
comparable stores convert at 12%.

Two comparison bases, and the difference matters more than it looks:

**Own baseline.** The scope against its own history. Immune to the peer-group
problem below, but blind to anything that moved the whole estate — a detector
on own-baseline alone reports every store as fine during an estate-wide
collapse, because they all fell together.

**Peer group.** The scope against comparable scopes in the same window. Catches
what own-baseline misses, and introduces the failure own-baseline does not have:
a peer group of two is not a peer group, and comparing a flagship against a
concession is comparing nothing. `minimum_peer_group` is a refusal, not a
warning.

Both are correlational. Neither establishes why, and the copy says so.

**The regression to watch for.** A scope below its peers *and* below its own
baseline is one finding, not two. The detector emits a single candidate naming
both comparisons, because two rows for one store's one problem is the ledger
failure dedupe exists to prevent, arriving through a different door.
"""

from __future__ import annotations

import statistics
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
    score_confidence,
)


class ComparisonBasis(StrEnum):
    OWN_BASELINE = "own_baseline"
    PEER_GROUP = "peer_group"
    EITHER = "either"


class BaselineComparisonConfig(DetectorConfig):
    gap_type: str = Field(min_length=1)
    canonical_entity: str = Field(min_length=1)
    metric_name: str = Field(min_length=1)
    scope_dimension: str = "location_id"
    scope_type: ScopeType = ScopeType.LOCATION
    unit: Unit = Unit.RATIO

    basis: ComparisonBasis = ComparisonBasis.EITHER

    # How far below the comparison point before it is a finding, as a share of
    # that point. Relative so one config works across metrics whose scales
    # differ by orders of magnitude.
    threshold_shortfall: Decimal = Decimal("0.15")
    severity_high_shortfall: Decimal = Decimal("0.30")
    severity_critical_shortfall: Decimal = Decimal("0.50")

    # A peer group of two is not a peer group. This is a refusal to compare,
    # not a caveat on the comparison.
    minimum_peer_group: int = Field(default=5, ge=2)

    # Peers are compared against the median, not the mean: one flagship store
    # drags a mean upward and reports every ordinary store as underperforming.
    @model_validator(mode="after")
    def _thresholds_are_ordered(self) -> BaselineComparisonConfig:
        if not (
            self.threshold_shortfall
            <= self.severity_high_shortfall
            <= self.severity_critical_shortfall
        ):
            raise ValueError(
                "shortfall thresholds must increase: threshold <= high <= critical, got "
                f"{self.threshold_shortfall}, {self.severity_high_shortfall}, "
                f"{self.severity_critical_shortfall}"
            )
        return self


class BaselineComparisonDetector(Detector):
    """A scope below its own history, its peers, or both.

    Readings carry `baseline_value` in their dimensions when the scope has one.
    The peer median is computed across the readings in the batch, which is what
    makes the peer comparison a property of the window rather than of a stored
    aggregate that may be stale.
    """

    key = "baseline_comparison"
    config_model = BaselineComparisonConfig

    def __init__(self, config: BaselineComparisonConfig) -> None:
        super().__init__(config)
        self.config: BaselineComparisonConfig = config
        self.gap_type = config.gap_type

    def detect(
        self, readings: Sequence[MetricReading], context: DetectorContext
    ) -> list[GapCandidate]:
        config = self.config
        measured = [r for r in readings if r.value is not None]
        peer_median = self._peer_median(measured)

        candidates: list[GapCandidate] = []
        for reading in measured:
            assert reading.value is not None  # noqa: S101 - filtered above
            comparisons = self._comparisons(reading, peer_median)
            if not comparisons:
                continue

            # The worst shortfall drives severity and the delta; every
            # comparison is named in the summary. One problem, one row.
            basis, reference, shortfall = max(comparisons, key=lambda c: c[2])

            scope_id = reading.dimension(config.scope_dimension)
            observations = reading.denominator or 0
            confidence = self._score(reading, observations, comparisons, len(measured))

            candidates.append(
                GapCandidate(
                    gap_type=config.gap_type,
                    pack_key=config.pack_key,
                    scope_type=config.scope_type,
                    scope_id=scope_id,
                    title=(
                        f"{config.metric_name} at {scope_id} is {shortfall:.0%} below "
                        f"{self._basis_phrase(basis)}"
                    ),
                    summary=self._summary(scope_id, reading.value, observations, comparisons),
                    metric_key=reading.metric_key,
                    metric_version=reading.metric_version,
                    observed_value=reading.value,
                    expected_value=reference,
                    unit=config.unit,
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
                    exposure=None,
                    reason_codes=tuple(f"below_{b.value}" for b, _, _ in comparisons),
                    correlation_keys=(f"metric:{reading.metric_identity}",),
                )
            )
        return candidates

    def _peer_median(self, readings: Sequence[MetricReading]) -> Decimal | None:
        """The median, never the mean.

        One flagship store drags a mean upward and reports every ordinary store
        as underperforming, which is a detector that fires on the shape of the
        estate rather than on anything that changed.
        """
        if len(readings) < self.config.minimum_peer_group:
            return None
        values = sorted(r.value for r in readings if r.value is not None)
        return Decimal(str(statistics.median(values)))

    def _comparisons(
        self, reading: MetricReading, peer_median: Decimal | None
    ) -> list[tuple[ComparisonBasis, Decimal, Decimal]]:
        """Every basis this reading falls short against, with the shortfall."""
        config = self.config
        assert reading.value is not None  # noqa: S101 - caller filters
        found: list[tuple[ComparisonBasis, Decimal, Decimal]] = []

        if config.basis in (ComparisonBasis.OWN_BASELINE, ComparisonBasis.EITHER):
            raw = reading.dimensions.get("baseline_value")
            if raw is not None:
                baseline = Decimal(raw)
                if baseline > 0:
                    shortfall = (baseline - reading.value) / baseline
                    if shortfall >= config.threshold_shortfall:
                        found.append((ComparisonBasis.OWN_BASELINE, baseline, shortfall))

        if (
            config.basis in (ComparisonBasis.PEER_GROUP, ComparisonBasis.EITHER)
            and peer_median is not None
            and peer_median > 0
        ):
            shortfall = (peer_median - reading.value) / peer_median
            if shortfall >= config.threshold_shortfall:
                found.append((ComparisonBasis.PEER_GROUP, peer_median, shortfall))

        return found

    def _score(
        self,
        reading: MetricReading,
        observations: int,
        comparisons: Sequence[tuple[ComparisonBasis, Decimal, Decimal]],
        peer_count: int,
    ) -> ConfidenceResult:
        components = {
            Component.SAMPLE_SIZE: SampleSizeScore(
                observations=observations, minimum=self.config.minimum_observations
            ).value,
            # Two independent comparisons agreeing fit the question better
            # than one. Note this raises *fit*, not the whole score: a peer
            # comparison resting on a thin group still pulls the total down
            # through source agreement, and it should. "Two comparisons agree"
            # and "both comparisons are well founded" are different claims.
            Component.DETECTOR_FIT: 1.0 if len(comparisons) > 1 else 0.7,
        }
        if any(b is ComparisonBasis.PEER_GROUP for b, _, _ in comparisons):
            # A peer comparison is only as good as the group behind it. Scored
            # against twice the minimum so a group scraping past the floor does
            # not read as a confident comparison.
            components[Component.SOURCE_AGREEMENT] = min(
                1.0, peer_count / (self.config.minimum_peer_group * 2)
            )
        return score_confidence(components)

    @staticmethod
    def _basis_phrase(basis: ComparisonBasis) -> str:
        return "its own baseline" if basis is ComparisonBasis.OWN_BASELINE else "its peer group"

    def _summary(
        self,
        scope_id: str,
        observed: Decimal,
        observations: int,
        comparisons: Sequence[tuple[ComparisonBasis, Decimal, Decimal]],
    ) -> str:
        """Names every comparison, and claims no cause.

        A scope below its peers and below its own baseline is one finding with
        two supporting comparisons — not two findings, and not a claim about
        what changed.
        """
        parts = [
            f"{shortfall:.0%} below {self._basis_phrase(basis)} of {reference}"
            for basis, reference, shortfall in comparisons
        ]
        return (
            f"{self.config.metric_name} at {scope_id} was {observed} over {observations} "
            f"observations: {', and '.join(parts)}. These are comparisons, not "
            f"explanations — nothing here establishes what differs."
        )

    def _severity(self, shortfall: Decimal) -> Severity:
        if shortfall >= self.config.severity_critical_shortfall:
            return Severity.CRITICAL
        if shortfall >= self.config.severity_high_shortfall:
            return Severity.HIGH
        return Severity.MEDIUM


__all__ = [
    "BaselineComparisonConfig",
    "BaselineComparisonDetector",
    "ComparisonBasis",
]
