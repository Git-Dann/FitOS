"""Data-quality detectors: freshness, completeness and schema drift.

Not a second-class family. A data-quality gap suppresses or de-confidences the
business gaps that depend on the same source, and that linkage is the reason
these exist as gaps rather than as an operational dashboard nobody reads. The
alternative — a silent feed and a calm-looking ledger — is the most expensive
way for this product to be wrong.

Three classes, three different shapes of "the data is not what it claims":

**Freshness.** The source is later than it promised. The gap is raised against
the *declared* cadence, not against a global constant, because a feed that
promises hourly and a feed that promises weekly are both healthy at very
different ages.

**Completeness.** Fewer records arrived than expected, or too many were
rejected. Both are the same finding from the consumer's side: the metric is
computed over a denominator that is missing rows nobody can name.

**Schema drift.** The observed shape differs from the declared one. Fires on a
single occurrence rather than a rate, because one unexpected column is a
contract change and averaging it away is how a breaking change ships quietly.
None of these carry exposure. A late feed is not money, and attaching a figure
to it would mean inventing one — the exposure rules exist precisely to stop
that. They carry severity and confidence, which is what a data-quality finding
actually has to say.
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
    freshness_score,
    score_confidence,
)

# Reason codes the pipeline's suppression stage keys on. Kept here beside the
# detectors that emit them, so adding a class and forgetting the linkage is a
# visible omission rather than a silent one.
FRESHNESS_GAP_TYPE = "source_freshness_breach"
COMPLETENESS_GAP_TYPE = "data_completeness_drop"
SCHEMA_DRIFT_GAP_TYPE = "schema_drift"


class FreshnessConfig(DetectorConfig):
    """One source's promised cadence and the tolerance around it."""

    scope_dimension: str = "source_key"
    scope_type: ScopeType = ScopeType.ORGANIZATION
    canonical_entity: str = "connector_run"

    # What the source declared. A gap is measured against this, never against a
    # global constant: hourly and weekly feeds are both healthy at ages that
    # differ by two orders of magnitude.
    expected_latency_seconds: float = Field(gt=0)
    # How far past the promise before it is worth raising. Multiplicative so one
    # value works across cadences.
    breach_multiplier: float = Field(default=2.0, ge=1.0)
    severity_high_multiplier: float = Field(default=4.0, ge=1.0)
    severity_critical_multiplier: float = Field(default=12.0, ge=1.0)

    # Freshness is about arrival, not about volume, so there is no sample
    # minimum to meet. One late delivery is the whole finding.
    minimum_observations: int = 0


class FreshnessDetector(Detector):
    """A source is later than the cadence it declared."""

    key = "source_freshness"
    gap_type = FRESHNESS_GAP_TYPE
    config_model = FreshnessConfig

    def __init__(self, config: FreshnessConfig) -> None:
        super().__init__(config)
        self.config: FreshnessConfig = config

    def detect(
        self, readings: Sequence[MetricReading], context: DetectorContext
    ) -> list[GapCandidate]:
        config = self.config
        candidates: list[GapCandidate] = []

        for reading in readings:
            if reading.source_max_timestamp is None:
                # Unknown recency is not freshness. It is a different finding —
                # the source has never reported — and calling it "0 seconds
                # old" would be the most flattering possible guess.
                continue

            age = (context.window.as_of - reading.source_max_timestamp).total_seconds()
            allowed = config.expected_latency_seconds * config.breach_multiplier
            if age <= allowed:
                continue

            scope_id = reading.dimension(config.scope_dimension)
            overdue = age / config.expected_latency_seconds

            candidates.append(
                GapCandidate(
                    gap_type=self.gap_type,
                    pack_key=config.pack_key,
                    scope_type=config.scope_type,
                    scope_id=scope_id,
                    title=f"{scope_id} is {self._human(age)} behind its expected cadence",
                    summary=(
                        f"The newest record from {scope_id} is {self._human(age)} old, "
                        f"against a declared cadence of "
                        f"{self._human(config.expected_latency_seconds)}. Metrics built on "
                        f"this source describe an older world than they appear to."
                    ),
                    metric_key=reading.metric_key,
                    metric_version=reading.metric_version,
                    observed_value=Decimal(int(age)),
                    expected_value=Decimal(int(config.expected_latency_seconds)),
                    unit=Unit.SECONDS,
                    window=context.window,
                    evidence=(
                        EvidenceRef.from_reading(
                            reading,
                            canonical_entity=config.canonical_entity,
                            window=context.window,
                        ),
                    ),
                    severity=self._severity(overdue),
                    confidence=self._score(age),
                    # No exposure. A late feed is not money, and attaching a
                    # figure would mean inventing one.
                    exposure=None,
                    reason_codes=("source_late",),
                    data_freshness_seconds=int(age),
                    correlation_keys=(f"source:{scope_id}", f"metric:{reading.metric_identity}"),
                )
            )
        return candidates

    def _score(self, age: float) -> ConfidenceResult:
        """High confidence by construction, and honestly so.

        "This timestamp is older than that timestamp" is an observation, not an
        inference. The only component that applies is detector fit; sample size
        and source agreement are meaningless for a single arrival time, so they
        are dropped rather than guessed.
        """
        return score_confidence({Component.DETECTOR_FIT: 1.0})

    def _severity(self, overdue: float) -> Severity:
        if overdue >= self.config.severity_critical_multiplier:
            return Severity.CRITICAL
        if overdue >= self.config.severity_high_multiplier:
            return Severity.HIGH
        return Severity.MEDIUM

    @staticmethod
    def _human(seconds: float) -> str:
        if seconds < 90:
            return f"{int(seconds)} seconds"
        if seconds < 5400:
            return f"{int(seconds / 60)} minutes"
        if seconds < 172_800:
            return f"{int(seconds / 3600)} hours"
        return f"{int(seconds / 86_400)} days"


class CompletenessConfig(DetectorConfig):
    scope_dimension: str = "source_key"
    scope_type: ScopeType = ScopeType.ORGANIZATION
    canonical_entity: str = "connector_run"

    # Accepted records as a share of everything the source delivered. Below this
    # the metrics built on it are computed over a denominator missing rows
    # nobody can name.
    expected_completeness: Decimal = Decimal("1.00")
    threshold_completeness: Decimal = Decimal("0.98")
    severity_high_completeness: Decimal = Decimal("0.90")
    severity_critical_completeness: Decimal = Decimal("0.70")

    minimum_observations: int = 1


class CompletenessDetector(Detector):
    """Fewer records arrived, or more were rejected, than expected."""

    key = "data_completeness"
    gap_type = COMPLETENESS_GAP_TYPE
    config_model = CompletenessConfig

    def __init__(self, config: CompletenessConfig) -> None:
        super().__init__(config)
        self.config: CompletenessConfig = config

    def detect(
        self, readings: Sequence[MetricReading], context: DetectorContext
    ) -> list[GapCandidate]:
        config = self.config
        candidates: list[GapCandidate] = []

        for reading in readings:
            if reading.value is None:
                # No completeness ratio means nothing arrived to measure. That
                # is a freshness or connection finding, not this one, and
                # reporting it as 0% complete would double-count the outage.
                continue
            if reading.value >= config.threshold_completeness:
                continue

            scope_id = reading.dimension(config.scope_dimension)
            delivered = reading.denominator or 0
            missing = int((Decimal(1) - reading.value) * Decimal(delivered))

            candidates.append(
                GapCandidate(
                    gap_type=self.gap_type,
                    pack_key=config.pack_key,
                    scope_type=config.scope_type,
                    scope_id=scope_id,
                    title=f"{scope_id} delivered {reading.value:.1%} of expected records",
                    summary=(
                        f"{missing} of {delivered} records from {scope_id} were rejected or "
                        f"never arrived in this window. Metrics over this source are "
                        f"computed on a denominator that is missing rows."
                    ),
                    metric_key=reading.metric_key,
                    metric_version=reading.metric_version,
                    observed_value=reading.value,
                    expected_value=config.expected_completeness,
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
                    confidence=score_confidence(
                        {Component.DETECTOR_FIT: 1.0, Component.COMPLETENESS: float(reading.value)}
                    ),
                    exposure=None,
                    reason_codes=("records_missing",),
                    correlation_keys=(f"source:{scope_id}", f"metric:{reading.metric_identity}"),
                )
            )
        return candidates

    def _severity(self, completeness: Decimal) -> Severity:
        if completeness <= self.config.severity_critical_completeness:
            return Severity.CRITICAL
        if completeness <= self.config.severity_high_completeness:
            return Severity.HIGH
        return Severity.MEDIUM


class SchemaDriftConfig(DetectorConfig):
    scope_dimension: str = "source_key"
    scope_type: ScopeType = ScopeType.ORGANIZATION
    canonical_entity: str = "connector_run"

    # One occurrence is the finding. A rate would average a breaking contract
    # change into nothing, which is exactly how one ships quietly.
    minimum_observations: int = 0
    severity_on_removed_field: Severity = Severity.CRITICAL
    severity_on_type_change: Severity = Severity.HIGH
    severity_on_new_field: Severity = Severity.LOW


class SchemaDriftDetector(Detector):
    """The observed shape differs from the declared one.

    Readings carry the drift in their dimensions: `drift_kind` is one of
    `removed_field`, `type_change` or `new_field`, and `field_name` names it.
    A removed field is critical because everything downstream of it is now
    computing over nulls it cannot see.
    """

    key = "schema_drift"
    gap_type = SCHEMA_DRIFT_GAP_TYPE
    config_model = SchemaDriftConfig

    DRIFT_KINDS = ("removed_field", "type_change", "new_field")

    def __init__(self, config: SchemaDriftConfig) -> None:
        super().__init__(config)
        self.config: SchemaDriftConfig = config

    def detect(
        self, readings: Sequence[MetricReading], context: DetectorContext
    ) -> list[GapCandidate]:
        config = self.config
        candidates: list[GapCandidate] = []

        for reading in readings:
            kind = reading.dimensions.get("drift_kind")
            if kind is None:
                continue
            if kind not in self.DRIFT_KINDS:
                # An unrecognised drift kind is a bug in whatever produced the
                # reading, not a finding to guess a severity for. Refusing is
                # the only honest option; the run record carries the error.
                raise ValueError(
                    f"unknown drift_kind {kind!r}; expected one of {list(self.DRIFT_KINDS)}"
                )

            scope_id = reading.dimension(config.scope_dimension)
            field = reading.dimensions.get("field_name", "an unnamed field")

            candidates.append(
                GapCandidate(
                    gap_type=self.gap_type,
                    pack_key=config.pack_key,
                    scope_type=config.scope_type,
                    scope_id=scope_id,
                    title=f"{scope_id} schema changed: {kind.replace('_', ' ')} ({field})",
                    summary=(
                        f"The shape delivered by {scope_id} no longer matches the declared "
                        f"one: {kind.replace('_', ' ')} affecting {field}. Mappings and "
                        f"metrics built on the declared shape may be reading nulls."
                    ),
                    metric_key=reading.metric_key,
                    metric_version=reading.metric_version,
                    # One occurrence against zero expected. The comparison is
                    # what makes it a gap rather than a log line.
                    observed_value=Decimal(1),
                    expected_value=Decimal(0),
                    unit=Unit.COUNT,
                    window=context.window,
                    evidence=(
                        EvidenceRef.from_reading(
                            reading,
                            canonical_entity=config.canonical_entity,
                            window=context.window,
                        ),
                    ),
                    severity=self._severity(kind),
                    confidence=score_confidence({Component.DETECTOR_FIT: 1.0}),
                    exposure=None,
                    reason_codes=(kind,),
                    correlation_keys=(f"source:{scope_id}",),
                )
            )
        return candidates

    def _severity(self, kind: str) -> Severity:
        return {
            "removed_field": self.config.severity_on_removed_field,
            "type_change": self.config.severity_on_type_change,
            "new_field": self.config.severity_on_new_field,
        }[kind]


__all__ = [
    "COMPLETENESS_GAP_TYPE",
    "FRESHNESS_GAP_TYPE",
    "SCHEMA_DRIFT_GAP_TYPE",
    "CompletenessConfig",
    "CompletenessDetector",
    "FreshnessConfig",
    "FreshnessDetector",
    "SchemaDriftConfig",
    "SchemaDriftDetector",
    "freshness_score",
]
