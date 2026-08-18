"""The detector framework: typed I/O, versioned config, replay, run records.

The framework's value is that twelve detector classes behave identically where
it matters — refusing on thin data, ordering their output, surviving each
other's exceptions, recording what they did. Each of those is tested here once
rather than twelve times approximately.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fitos_worker.detectors.base import (
    Detector,
    DetectorConfig,
    DetectorContext,
    EvidenceRef,
    GapCandidate,
    MetricReading,
    ObservationWindow,
    ScopeType,
    Severity,
    Unit,
    candidate_fingerprint,
    utc,
)
from fitos_worker.detectors.confidence import Component, ConfidenceBand, score_confidence

RULE_ID = UUID("11111111-1111-1111-1111-111111111111")
WINDOW = ObservationWindow(start=utc(2026, 8, 1), end=utc(2026, 8, 2))
CONTEXT = DetectorContext(
    organization_id=UUID("22222222-2222-2222-2222-222222222222"),
    window=WINDOW,
    as_of=WINDOW.end,
)


def reading(
    *,
    scope: str = "store-1",
    value: Decimal | None = Decimal("0.4"),
    denominator: int | None = 100,
) -> MetricReading:
    return MetricReading(
        metric_key="stock_discrepancy_rate",
        metric_version=1,
        query_hash="deadbeef",
        dimensions={"location_id": scope},
        value=value,
        denominator=denominator,
        captured_at=utc(2026, 8, 2),
    )


def evidence() -> EvidenceRef:
    return EvidenceRef(
        canonical_entity="fact_stock_count",
        metric_key="stock_discrepancy_rate",
        metric_version=1,
        query_hash="deadbeef",
        observation_window=WINDOW.to_json(),
        captured_at=utc(2026, 8, 2),
    )


def candidate(*, scope: str = "store-1", gap_type: str = "t") -> GapCandidate:
    return GapCandidate(
        gap_type=gap_type,
        pack_key="retail_omnichannel",
        scope_type=ScopeType.LOCATION,
        scope_id=scope,
        title="t",
        summary="s",
        metric_key="stock_discrepancy_rate",
        metric_version=1,
        observed_value=Decimal("0.4"),
        expected_value=Decimal("0.02"),
        unit=Unit.RATIO,
        window=WINDOW,
        evidence=(evidence(),),
        severity=Severity.MEDIUM,
        confidence=score_confidence({Component.SAMPLE_SIZE: 0.9}),
    )


class Spy(Detector):
    key = "spy"
    gap_type = "spy_gap"

    def __init__(self, config: DetectorConfig, *, scopes: list[str] | None = None) -> None:
        super().__init__(config)
        # `scopes if scopes is not None`, not `scopes or` — an explicit empty
        # list is how a test says "this detector found nothing", and the falsy
        # default would quietly turn that into "it found store-1".
        self.scopes = scopes if scopes is not None else ["store-1"]
        self.seen: list[MetricReading] = []

    def detect(
        self, readings: Sequence[MetricReading], context: DetectorContext
    ) -> list[GapCandidate]:
        self.seen = list(readings)
        if not readings:
            return []
        return [candidate(scope=s, gap_type=self.gap_type) for s in self.scopes]


class Exploding(Detector):
    key = "exploding"
    gap_type = "never"

    def detect(
        self, readings: Sequence[MetricReading], context: DetectorContext
    ) -> list[GapCandidate]:
        raise RuntimeError("the metric store timed out")


def config(**kwargs: object) -> DetectorConfig:
    base: dict[str, object] = {
        "rule_id": RULE_ID,
        "version": 1,
        "pack_key": "retail_omnichannel",
    }
    base.update(kwargs)
    return DetectorConfig(**base)  # type: ignore[arg-type]


# --- the observation window -------------------------------------------------


def test_a_window_is_half_open_and_ordered() -> None:
    with pytest.raises(ValueError, match="not before"):
        ObservationWindow(start=utc(2026, 8, 2), end=utc(2026, 8, 1))
    with pytest.raises(ValueError, match="not before"):
        ObservationWindow(start=utc(2026, 8, 1), end=utc(2026, 8, 1))


def test_a_naive_window_is_refused() -> None:
    """A naive datetime compares fine against another naive one and raises
    TypeError the first time it meets a real reading."""
    with pytest.raises(ValueError, match="timezone-aware"):
        ObservationWindow(start=datetime(2026, 8, 1), end=utc(2026, 8, 2))


def test_as_of_is_the_window_end_not_the_write_time() -> None:
    assert WINDOW.as_of == WINDOW.end


def test_a_naive_as_of_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        DetectorContext(organization_id=uuid4(), window=WINDOW, as_of=datetime(2026, 8, 2))


# --- the sufficiency refusal ------------------------------------------------


def test_a_thin_reading_is_refused_before_the_detector_sees_it() -> None:
    """ "We do not have enough data to say" and "we looked and it is fine" are
    different answers. The detector never gets the chance to conflate them."""
    spy = Spy(config(minimum_observations=30))
    result = spy.run([reading(denominator=29)], CONTEXT)

    assert spy.seen == []
    assert result.insufficient_readings == 1
    assert result.readings_considered == 1


def test_a_reading_at_the_minimum_is_sufficient() -> None:
    spy = Spy(config(minimum_observations=30))
    spy.run([reading(denominator=30)], CONTEXT)
    assert len(spy.seen) == 1


def test_a_reading_with_no_denominator_is_insufficient() -> None:
    """An unknown denominator is not a large one."""
    spy = Spy(config(minimum_observations=30))
    result = spy.run([reading(denominator=None)], CONTEXT)

    assert spy.seen == []
    assert result.insufficient_readings == 1


def test_a_zero_minimum_accepts_everything() -> None:
    """Some detectors genuinely have no denominator — a schema-drift detector
    fires on one bad record."""
    spy = Spy(config(minimum_observations=0))
    spy.run([reading(denominator=None)], CONTEXT)
    assert len(spy.seen) == 1


def test_a_run_that_refused_everything_is_distinguishable_from_a_clean_run() -> None:
    """The indistinguishability is the whole reason the field exists."""
    thin = Spy(config(minimum_observations=30)).run(
        [reading(denominator=1) for _ in range(400)], CONTEXT
    )
    clean = Spy(config(minimum_observations=30), scopes=[]).run([reading()], CONTEXT)

    assert thin.to_record()["candidates_produced"] == 0
    assert clean.to_record()["candidates_produced"] == 0
    assert thin.to_record()["insufficient_readings"] == 400
    assert clean.to_record()["insufficient_readings"] == 0


# --- isolation and errors ---------------------------------------------------


def test_a_detector_that_raises_does_not_take_the_run_with_it() -> None:
    result = Exploding(config()).run([reading()], CONTEXT)

    assert result.candidates == ()
    assert not result.succeeded
    assert result.errors == ("RuntimeError: the metric store timed out",)


def test_a_failed_detector_does_not_look_like_one_that_found_nothing() -> None:
    failed = Exploding(config()).run([reading()], CONTEXT)
    empty = Spy(config(), scopes=[]).run([reading()], CONTEXT)

    assert failed.candidates == empty.candidates == ()
    assert not failed.succeeded
    assert empty.succeeded


def test_a_disabled_detector_records_why_it_did_nothing() -> None:
    result = Spy(config(enabled=False)).run([reading()], CONTEXT)

    assert result.candidates == ()
    assert result.skipped_reason == "detector disabled"
    assert result.succeeded


# --- replay -----------------------------------------------------------------


def test_output_order_is_stable_regardless_of_input_order() -> None:
    """Without this, dict iteration order inside a detector becomes part of the
    observable output and golden fixtures start flapping."""
    forward = Spy(config(), scopes=["store-3", "store-1", "store-2"]).run([reading()], CONTEXT)
    backward = Spy(config(), scopes=["store-2", "store-3", "store-1"]).run([reading()], CONTEXT)

    assert [c.scope_id for c in forward.candidates] == ["store-1", "store-2", "store-3"]
    assert [c.scope_id for c in backward.candidates] == [c.scope_id for c in forward.candidates]


def test_the_same_inputs_produce_the_same_fingerprints() -> None:
    first = Spy(config()).run([reading()], CONTEXT)
    second = Spy(config()).run([reading()], CONTEXT)

    assert [candidate_fingerprint(c) for c in first.candidates] == [
        candidate_fingerprint(c) for c in second.candidates
    ]


def test_the_fingerprint_notices_a_value_change_a_repr_would_hide() -> None:
    """A repr changes when a field is renamed, which is churn, and does not
    change when a Decimal quietly becomes a float, which is a bug."""
    base = candidate()
    moved = GapCandidate(
        **{
            **{f.name: getattr(base, f.name) for f in base.__dataclass_fields__.values()},
            "observed_value": Decimal("0.41"),
        }
    )
    assert candidate_fingerprint(base) != candidate_fingerprint(moved)


# --- versioned config -------------------------------------------------------


def test_an_unknown_config_key_is_refused() -> None:
    """A typo'd threshold that is silently ignored leaves the detector running
    on a default nobody chose."""
    with pytest.raises(ValueError, match="threshhold_rate"):
        DetectorConfig(
            rule_id=RULE_ID,
            version=1,
            pack_key="p",
            threshhold_rate=0.5,  # type: ignore[call-arg]
        )


def test_the_config_fingerprint_changes_when_a_threshold_changes() -> None:
    """A threshold change becomes a visible event rather than something inferred
    from a gap that stopped firing."""
    assert config(minimum_observations=30).fingerprint() != (
        config(minimum_observations=50).fingerprint()
    )


def test_the_config_fingerprint_is_stable_across_processes() -> None:
    assert config().fingerprint() == config().fingerprint()


def test_the_version_lands_on_the_run_record() -> None:
    record = Spy(config(version=7)).run([reading()], CONTEXT).to_record()
    assert record["rule_version"] == 7
    assert record["rule_id"] == str(RULE_ID)


def test_a_detector_refuses_a_config_of_the_wrong_type() -> None:
    class Narrow(DetectorConfig):
        pass

    class Fussy(Spy):
        config_model = Narrow

    with pytest.raises(TypeError, match="takes Narrow"):
        Fussy(config())


def test_a_config_version_below_one_is_refused() -> None:
    with pytest.raises(ValueError, match="version"):
        DetectorConfig(rule_id=RULE_ID, version=0, pack_key="p")


# --- the candidate contract -------------------------------------------------


def test_a_candidate_without_evidence_cannot_be_constructed() -> None:
    """Invariant 1, enforced where the detector runs rather than at INSERT time —
    a database refusal arrives detached from the code that caused it."""
    with pytest.raises(ValueError, match="at least one evidence reference"):
        GapCandidate(
            gap_type="t",
            pack_key="p",
            scope_type=ScopeType.LOCATION,
            scope_id="store-1",
            title="t",
            summary="s",
            metric_key="m",
            metric_version=1,
            observed_value=Decimal(1),
            expected_value=Decimal(0),
            unit=Unit.RATIO,
            window=WINDOW,
            evidence=(),
            severity=Severity.MEDIUM,
            confidence=score_confidence({Component.SAMPLE_SIZE: 0.9}),
        )


def test_a_candidate_with_no_delta_is_refused() -> None:
    """A gap with no comparison is a measurement, not a finding."""
    with pytest.raises(ValueError, match="no delta"):
        GapCandidate(
            gap_type="t",
            pack_key="p",
            scope_type=ScopeType.LOCATION,
            scope_id="store-1",
            title="t",
            summary="s",
            metric_key="m",
            metric_version=1,
            observed_value=Decimal("0.5"),
            expected_value=Decimal("0.5"),
            unit=Unit.RATIO,
            window=WINDOW,
            evidence=(evidence(),),
            severity=Severity.MEDIUM,
            confidence=score_confidence({Component.SAMPLE_SIZE: 0.9}),
        )


def test_percentage_delta_is_null_against_a_zero_baseline() -> None:
    """Not infinity, and not an arbitrary cap: both invent a figure and both
    look like data."""
    zero_baseline = GapCandidate(
        gap_type="t",
        pack_key="p",
        scope_type=ScopeType.LOCATION,
        scope_id="store-1",
        title="t",
        summary="s",
        metric_key="m",
        metric_version=1,
        observed_value=Decimal("0.5"),
        expected_value=Decimal(0),
        unit=Unit.RATIO,
        window=WINDOW,
        evidence=(evidence(),),
        severity=Severity.MEDIUM,
        confidence=score_confidence({Component.SAMPLE_SIZE: 0.9}),
    )
    assert zero_baseline.percentage_delta is None
    assert zero_baseline.absolute_delta == Decimal("0.5")


def test_percentage_delta_keeps_its_sign() -> None:
    """Direction is information: below band and above band are different
    findings, and an absolute value would erase which one this is."""
    assert candidate().percentage_delta is not None
    assert candidate().percentage_delta > 0  # type: ignore[operator]


def test_a_candidate_without_a_scope_is_refused() -> None:
    with pytest.raises(ValueError, match="scope_id is required"):
        GapCandidate(
            gap_type="t",
            pack_key="p",
            scope_type=ScopeType.LOCATION,
            scope_id="",
            title="t",
            summary="s",
            metric_key="m",
            metric_version=1,
            observed_value=Decimal(1),
            expected_value=Decimal(0),
            unit=Unit.RATIO,
            window=WINDOW,
            evidence=(evidence(),),
            severity=Severity.MEDIUM,
            confidence=score_confidence({Component.SAMPLE_SIZE: 0.9}),
        )


# --- readings ---------------------------------------------------------------


def test_a_missing_dimension_names_what_it_has() -> None:
    with pytest.raises(KeyError, match="channel"):
        reading().dimension("channel")


def test_the_metric_identity_pins_the_version() -> None:
    assert reading().metric_identity == "stock_discrepancy_rate@v1"


# --- evidence ---------------------------------------------------------------


def test_evidence_carries_the_query_hash_and_window() -> None:
    ref = EvidenceRef.from_reading(reading(), canonical_entity="fact_stock_count", window=WINDOW)
    assert ref.query_hash == "deadbeef"
    assert ref.observation_window == WINDOW.to_json()
    assert ref.metric_version == 1
    assert ref.sensitivity_classification == "internal"


def test_evidence_records_the_dimensions_as_query_parameters() -> None:
    """Without these the reference resolves to the whole metric rather than to
    the row the gap is about."""
    ref = EvidenceRef.from_reading(
        reading(scope="store-9"), canonical_entity="fact_stock_count", window=WINDOW
    )
    assert ref.query_parameters == {"location_id": "store-9"}


def test_evidence_is_immutable() -> None:
    ref = EvidenceRef.from_reading(reading(), canonical_entity="fact_stock_count", window=WINDOW)
    with pytest.raises(ValueError, match="frozen"):
        ref.query_hash = "tampered"


def test_an_evidence_ref_cannot_omit_the_metric_version() -> None:
    with pytest.raises(ValueError, match="metric_version"):
        EvidenceRef(  # type: ignore[call-arg]
            canonical_entity="fact_stock_count",
            metric_key="m",
            query_hash="h",
            observation_window=WINDOW.to_json(),
            captured_at=utc(2026, 8, 2),
        )


# --- the run record ---------------------------------------------------------


def test_the_run_record_carries_the_acceptance_fields() -> None:
    """The criterion names them: versions, query hash, window, thresholds,
    candidates, suppressions, errors."""
    record = (
        Spy(config(minimum_observations=30))
        .run([reading(), reading(denominator=2)], CONTEXT)
        .to_record()
    )

    assert record["rule_id"] == str(RULE_ID)
    assert record["rule_version"] == 1
    assert record["config_fingerprint"]
    assert record["window"] == WINDOW.to_json()
    assert record["readings_considered"] == 2
    assert record["insufficient_readings"] == 1
    assert record["candidates_produced"] == 1
    assert record["query_hashes"] == ["deadbeef"]
    assert record["errors"] == []


def test_the_run_record_is_json_serialisable() -> None:
    import json

    json.dumps(Spy(config()).run([reading()], CONTEXT).to_record())


def test_the_confidence_band_reaches_the_candidate() -> None:
    result = Spy(config()).run([reading()], CONTEXT)
    assert result.candidates[0].confidence.band is ConfidenceBand.HIGH


def test_utc_builds_aware_datetimes() -> None:
    assert utc(2026, 8, 1).tzinfo is UTC
    assert utc(2026, 8, 1, 13, 30) - utc(2026, 8, 1) == timedelta(hours=13, minutes=30)
