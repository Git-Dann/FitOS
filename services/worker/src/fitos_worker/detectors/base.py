"""The detector framework: versioned config, typed I/O, replay.

A detector turns governed metric readings into gap candidates. Everything about
that sentence is load-bearing:

**Governed readings in.** A detector never queries a raw or staging table and
never re-implements a formula. It asks for a metric by key and version and gets
back readings that the metric layer computed. This is what makes "a certified
metric returns the same value through Cube, the API and a dbt test" true of the
detector too, rather than true of everything except the detector.

**Candidates out, not gaps.** A detector produces `GapCandidate` values. It does
not write to the database, does not dedupe, does not suppress and does not
decide severity policy. Those are pipeline stages that run over every detector's
output identically, because a detector that dedupes for itself dedupes slightly
differently from the next one and the ledger fills with near-duplicates that
each look correct in isolation.

**Versioned config.** `rule_id` and `rule_version` land on every gap. A
threshold change is a version bump, because a gap raised last month must remain
explicable by the configuration that raised it — not by whatever the threshold
happens to be when somebody opens the gap.

**Replay.** `detect()` is a pure function of `(config, readings, as_of)`. No
clock, no network, no database. That is what makes a golden fixture meaningful:
the same fixture must produce byte-identical candidates forever, and if it does
not, either the detector changed or the framework did — and the fixture says
which. It also means a detector body is safe inside a Temporal workflow, though
in practice they run in activities because fetching the readings is I/O.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from fitos_worker.detectors.confidence import ConfidenceResult
from fitos_worker.detectors.exposure import Exposure


class Severity(StrEnum):
    """Ranking input, deliberately distinct from exposure.

    A £40 gap in a safety-critical process outranks a £4,000 one in a
    discretionary one. Collapsing the two into a single money ordering is how a
    ledger ends up sorted by revenue and ignored by the people who could fix
    things.
    """

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ScopeType(StrEnum):
    LOCATION = "location"
    PRODUCT_VARIANT = "product_variant"
    CHANNEL = "channel"
    CAMPAIGN = "campaign"
    ORGANIZATION = "organization"


class Unit(StrEnum):
    COUNT = "count"
    RATIO = "ratio"
    CURRENCY_MINOR = "currency_minor"
    SECONDS = "seconds"


@dataclass(frozen=True)
class ObservationWindow:
    """A half-open interval, `[start, end)`.

    Half-open because the alternative double-counts the boundary: two adjacent
    daily windows that both include midnight attribute the same record twice,
    and the resulting metric is wrong by an amount that depends on traffic at
    exactly the least memorable time of day.
    """

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("an observation window must be timezone-aware")
        if self.start >= self.end:
            raise ValueError(f"window start {self.start} is not before end {self.end}")

    @property
    def as_of(self) -> datetime:
        """The observation time a gap records. The window end, never the write time."""
        return self.end

    def to_json(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


@dataclass(frozen=True)
class MetricReading:
    """One governed metric value at one point in the metric's grain.

    `metric_identity` and `query_hash` travel with the value rather than being
    attached later. A reading that has been separated from the query that
    produced it cannot be turned into evidence, and evidence is the difference
    between a gap and an assertion.
    """

    metric_key: str
    metric_version: int
    query_hash: str
    dimensions: dict[str, str]
    value: Decimal | None
    denominator: int | None
    captured_at: datetime
    source_max_timestamp: datetime | None = None

    @property
    def metric_identity(self) -> str:
        return f"{self.metric_key}@v{self.metric_version}"

    def dimension(self, name: str) -> str:
        try:
            return self.dimensions[name]
        except KeyError as exc:
            raise KeyError(
                f"reading for {self.metric_identity} has no dimension {name!r}; "
                f"it has {sorted(self.dimensions)}"
            ) from exc


class EvidenceRef(BaseModel):
    """One resolvable pointer from a gap back to how a number was produced.

    Every field is required except the locator, because the point of an evidence
    reference is that a user reaches the metric definition, the source
    connection, the detector configuration and the supporting records *without
    guessing*. A reference with a null metric version is a reference that
    answers none of those.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    canonical_entity: str
    canonical_record_id: str | None = None
    source_connection_id: UUID | None = None
    source_record_locator: str | None = None
    metric_key: str
    metric_version: int
    query_hash: str
    query_parameters: dict[str, str] = Field(default_factory=dict)
    observation_window: dict[str, str]
    captured_at: datetime
    sensitivity_classification: str = "internal"

    @classmethod
    def from_reading(
        cls,
        reading: MetricReading,
        *,
        canonical_entity: str,
        window: ObservationWindow,
        sensitivity: str = "internal",
    ) -> EvidenceRef:
        return cls(
            canonical_entity=canonical_entity,
            metric_key=reading.metric_key,
            metric_version=reading.metric_version,
            query_hash=reading.query_hash,
            query_parameters=dict(reading.dimensions),
            observation_window=window.to_json(),
            captured_at=reading.captured_at,
            sensitivity_classification=sensitivity,
        )


@dataclass(frozen=True)
class GapCandidate:
    """What a detector produces. Not yet a gap.

    Dedupe, suppression, correlation and persistence all happen downstream, over
    every detector's output identically. A candidate that has already been
    deduped by its own detector cannot be deduped consistently with the others.

    The constructor enforces the aggregate invariants that are expressible here,
    so a detector cannot emit something the database would refuse. Finding out at
    `INSERT` time means the detector run has already done its work and the
    failure arrives detached from the code that caused it.
    """

    gap_type: str
    pack_key: str
    scope_type: ScopeType
    scope_id: str
    title: str
    summary: str

    metric_key: str
    metric_version: int
    observed_value: Decimal
    expected_value: Decimal
    unit: Unit

    window: ObservationWindow
    evidence: tuple[EvidenceRef, ...]
    severity: Severity
    confidence: ConfidenceResult

    exposure: Exposure | None = None
    reason_codes: tuple[str, ...] = ()
    recommended_actions: tuple[dict[str, str], ...] = ()
    data_freshness_seconds: int | None = None
    correlation_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Invariant 1: no gap without evidence.
        if not self.evidence:
            raise ValueError(
                f"{self.gap_type}: a candidate needs at least one evidence reference; "
                "a gap nobody can trace back to a query is an assertion"
            )
        if not self.scope_id:
            raise ValueError(f"{self.gap_type}: scope_id is required")
        # A gap with no comparison is not a gap — it is a reading.
        if self.observed_value == self.expected_value:
            raise ValueError(
                f"{self.gap_type}: observed equals expected ({self.observed_value}); "
                "a gap with no delta is a measurement, not a finding"
            )

    @property
    def absolute_delta(self) -> Decimal:
        return abs(self.observed_value - self.expected_value)

    @property
    def percentage_delta(self) -> Decimal | None:
        """Null when expected is zero, rather than infinity or an arbitrary cap.

        A percentage against a zero baseline has no meaning; presenting one as
        "∞%" or "100%" invents a figure and both look like data.
        """
        if self.expected_value == 0:
            return None
        return (self.observed_value - self.expected_value) / self.expected_value

    @property
    def currency(self) -> str | None:
        return self.exposure.currency if self.exposure else None

    def dedupe_key_material(self, organization_id: UUID, rule_id: UUID) -> str:
        """Deliberately excludes the window and the values (gap-model.md §6).

        The same problem in the same scope on consecutive days is the same gap.
        Including the window would produce one row per day, which is the exact
        failure the dedupe release gate tests for.
        """
        return "|".join(
            [
                str(organization_id),
                self.pack_key,
                self.gap_type,
                self.scope_type.value,
                self.scope_id,
                str(rule_id),
            ]
        )


class DetectorConfig(BaseModel):
    """Versioned detector configuration.

    `version` is not decoration. It lands on every gap as `rule_version`, and a
    gap raised in March has to stay explicable by the March configuration —
    otherwise reopening an old gap shows it judged against a threshold that did
    not exist when it fired.

    Subclasses add their own thresholds. `extra="forbid"` means a typo'd
    threshold key is a startup error rather than a silently ignored setting that
    leaves the detector running on defaults nobody chose.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: UUID
    version: int = Field(ge=1)
    pack_key: str = Field(min_length=1)
    enabled: bool = True

    # Minimum observations before this detector will make a claim. This is where
    # denominator_min_30 is enforced as a refusal rather than a build failure:
    # a small location with few observations is a correct value over few
    # observations, not a broken pipeline, but it is still not enough to
    # accuse anybody of anything.
    minimum_observations: int = Field(default=30, ge=0)

    def fingerprint(self) -> str:
        """Hash of the effective configuration, recorded on the detector run.

        Makes "the threshold changed" a visible, checkable event rather than
        something inferred from a gap that stopped firing.
        """
        material = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(material.encode()).hexdigest()


@dataclass(frozen=True)
class DetectorContext:
    """Everything a detector may know. Deliberately small.

    There is no database session, no HTTP client and no clock. A detector that
    could reach any of those would stop being replayable, and a golden fixture
    over a non-replayable function proves nothing at all.

    `as_of` is passed in rather than read, for the same reason: `datetime.now()`
    inside a detector makes yesterday's fixture fail tomorrow for a reason that
    has nothing to do with the detector.
    """

    organization_id: UUID
    window: ObservationWindow
    as_of: datetime
    display_timezone: str = "UTC"

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")


class Detector(ABC):
    """One detector class. Stateless, pure, versioned.

    Implementations override `detect`. The framework handles the sufficiency
    refusal, the ordering guarantee and the run record, so those behave
    identically across all twelve classes rather than twelve times approximately.
    """

    key: str
    gap_type: str
    config_model: type[DetectorConfig] = DetectorConfig

    def __init__(self, config: DetectorConfig) -> None:
        if not isinstance(config, self.config_model):
            raise TypeError(
                f"{type(self).__name__} takes {self.config_model.__name__}, "
                f"got {type(config).__name__}"
            )
        self.config = config

    @abstractmethod
    def detect(
        self, readings: Sequence[MetricReading], context: DetectorContext
    ) -> list[GapCandidate]:
        """Pure. No clock, no I/O, no randomness. Same inputs, same output."""

    def sufficient(self, reading: MetricReading) -> bool:
        """The precondition every detector shares.

        A reading whose denominator is below the configured minimum is not
        evidence of anything. Refusing here rather than raising a low-confidence
        gap is the honest choice: "we do not have enough data to say" and "we
        looked and it is fine" are different answers, and only one of them is
        true.
        """
        if self.config.minimum_observations == 0:
            return True
        if reading.denominator is None:
            return False
        return reading.denominator >= self.config.minimum_observations

    def run(self, readings: Sequence[MetricReading], context: DetectorContext) -> DetectorRunResult:
        """Run the detector and record what it did.

        Every number in the run record is counted here rather than by the
        detector, so a detector cannot under-report its own suppressions.
        """
        if not self.config.enabled:
            return DetectorRunResult(
                detector_key=self.key,
                rule_id=self.config.rule_id,
                rule_version=self.config.version,
                config_fingerprint=self.config.fingerprint(),
                window=context.window,
                readings_considered=0,
                candidates=(),
                insufficient_readings=0,
                errors=(),
                skipped_reason="detector disabled",
            )

        sufficient = [r for r in readings if self.sufficient(r)]
        insufficient = len(readings) - len(sufficient)

        errors: list[str] = []
        candidates: list[GapCandidate] = []
        try:
            candidates = self.detect(sufficient, context)
        except Exception as exc:
            # A detector that raises must not take the other eleven with it, and
            # must not look like a detector that found nothing. The run record
            # carries the error and the caller decides.
            errors.append(f"{type(exc).__name__}: {exc}")

        # Stable ordering, so a replay of the same fixture produces the same
        # sequence. Without it, dict iteration order in a detector body becomes
        # part of the observable output and a golden fixture starts flapping.
        candidates.sort(key=lambda c: (c.scope_type.value, c.scope_id, c.gap_type))

        return DetectorRunResult(
            detector_key=self.key,
            rule_id=self.config.rule_id,
            rule_version=self.config.version,
            config_fingerprint=self.config.fingerprint(),
            window=context.window,
            readings_considered=len(readings),
            candidates=tuple(candidates),
            insufficient_readings=insufficient,
            errors=tuple(errors),
        )


@dataclass(frozen=True)
class DetectorRunResult:
    """What one detector did, in enough detail to audit it.

    The acceptance criterion names the contents: versions, query hash, window,
    thresholds, candidates, suppressions, dedupe decisions, duration and errors.
    The first seven are here; duration and dedupe decisions are added by the
    pipeline, because a pure detector cannot time itself without a clock and has
    not seen the other detectors' output yet.
    """

    detector_key: str
    rule_id: UUID
    rule_version: int
    config_fingerprint: str
    window: ObservationWindow
    readings_considered: int
    candidates: tuple[GapCandidate, ...]
    insufficient_readings: int
    errors: tuple[str, ...] = ()
    skipped_reason: str | None = None
    query_hashes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def succeeded(self) -> bool:
        return not self.errors

    def query_hash_list(self) -> list[str]:
        """Every distinct query behind this run's candidates, sorted.

        Typed rather than only reachable through `to_record()`, so the caller
        that persists it is not casting `object` into a JSON column.
        """
        return sorted({ref.query_hash for c in self.candidates for ref in c.evidence})

    def to_record(self) -> dict[str, Any]:
        """The persisted run record.

        `readings_considered` and `insufficient_readings` are both stored: a run
        that examined 400 readings and refused 399 for insufficiency looks
        identical to a clean run that found nothing, unless the record says
        otherwise. That indistinguishability is the whole reason for the field.
        """
        return {
            "detector_key": self.detector_key,
            "rule_id": str(self.rule_id),
            "rule_version": self.rule_version,
            "config_fingerprint": self.config_fingerprint,
            "window": self.window.to_json(),
            "readings_considered": self.readings_considered,
            "insufficient_readings": self.insufficient_readings,
            "candidates_produced": len(self.candidates),
            "errors": list(self.errors),
            "skipped_reason": self.skipped_reason,
            "query_hashes": sorted({ref.query_hash for c in self.candidates for ref in c.evidence}),
        }


def candidate_fingerprint(candidate: GapCandidate) -> str:
    """A hash of everything a replay must reproduce.

    Golden fixtures compare this rather than a dataclass repr: a repr changes
    when a field is renamed, which is churn, and does not change when a
    Decimal quietly becomes a float, which is a bug.
    """
    material = {
        "gap_type": candidate.gap_type,
        "scope": [candidate.scope_type.value, candidate.scope_id],
        "metric": [candidate.metric_key, candidate.metric_version],
        "observed": str(candidate.observed_value),
        "expected": str(candidate.expected_value),
        "unit": candidate.unit.value,
        "severity": candidate.severity.value,
        "confidence": [candidate.confidence.score, candidate.confidence.band.value],
        "exposure": (
            [
                candidate.exposure.low_minor,
                candidate.exposure.base_minor,
                candidate.exposure.high_minor,
                candidate.exposure.currency,
            ]
            if candidate.exposure
            else None
        ),
        "reason_codes": sorted(candidate.reason_codes),
        "evidence": sorted(
            f"{ref.metric_key}@v{ref.metric_version}:{ref.query_hash}" for ref in candidate.evidence
        ),
        "window": candidate.window.to_json(),
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def utc(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
) -> datetime:
    """Timezone-aware construction for fixtures. Never a bare datetime.

    A naive datetime in a fixture is the quietest bug in this whole area: it
    compares fine against another naive one, and the first comparison against a
    real reading raises `TypeError` in production rather than in the test.
    """
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


__all__ = [
    "Detector",
    "DetectorConfig",
    "DetectorContext",
    "DetectorRunResult",
    "EvidenceRef",
    "GapCandidate",
    "MetricReading",
    "ObservationWindow",
    "ScopeType",
    "Severity",
    "Unit",
    "candidate_fingerprint",
    "utc",
]
