"""Detector golden fixtures.

A recorded input and its recorded output, compared on every run. The framework's
replay guarantee — `detect` is a pure function of `(config, readings, as_of)` —
is only worth anything if something checks it, and the natural place to break it
is a scoring tweak that looks harmless and quietly moves every gap in the estate.

The comparison is on `candidate_fingerprint`, not a dataclass repr. A repr
changes when a field is renamed, which is churn, and does not change when a
Decimal quietly becomes a float, which is a bug.

**Regenerating.** `FITOS_REGENERATE_GOLDEN=1 uv run pytest
services/worker/tests/test_golden_fixtures.py` rewrites the files. That is a
deliberate act with a visible diff, which is the point: a fixture that
regenerates itself on mismatch is a fixture that asserts nothing. The diff is
the review — if a scoring change moves fifty fingerprints, the pull request says
so.

Regeneration is refused when `CI` is set, and that guard is not hypothetical. It
was added after the variable leaked across two commands in one shell during this
build: what looked like a passing comparison had quietly rewritten the fixture
with the output of deliberately broken code, and the suite went green on a
mutation it was supposed to catch. In CI the same leak would turn every golden
test into a no-op that reports success, which is the exact failure CLAUDE.md
names — a check that finds nothing looks identical to one that works.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fitos_worker.detectors.attribution import (
    AttributionConfig,
    AttributionDetector,
    AttributionMethod,
)
from fitos_worker.detectors.base import (
    Detector,
    DetectorContext,
    MetricReading,
    ObservationWindow,
    candidate_fingerprint,
    utc,
)
from fitos_worker.detectors.baseline_comparison import (
    BaselineComparisonConfig,
    BaselineComparisonDetector,
)
from fitos_worker.detectors.data_quality import (
    CompletenessConfig,
    CompletenessDetector,
    FreshnessConfig,
    FreshnessDetector,
    SchemaDriftConfig,
    SchemaDriftDetector,
)
from fitos_worker.detectors.financial_leakage import (
    FinancialLeakageConfig,
    FinancialLeakageDetector,
)
from fitos_worker.detectors.funnel_drop import (
    FunnelDropConfig,
    FunnelDropDetector,
    FunnelStage,
)
from fitos_worker.detectors.ratio_threshold import (
    Direction,
    RatioThresholdConfig,
    RatioThresholdDetector,
)
from fitos_worker.detectors.source_mismatch import SourceMismatchConfig, SourceMismatchDetector

GOLDEN = Path(__file__).parent / "golden"
_REGENERATE_REQUESTED = bool(os.environ.get("FITOS_REGENERATE_GOLDEN"))
_ON_CI = bool(os.environ.get("CI"))
REGENERATE = _REGENERATE_REQUESTED and not _ON_CI

RULE = UUID("11111111-1111-1111-1111-111111111111")
WINDOW = ObservationWindow(start=utc(2026, 8, 1), end=utc(2026, 8, 2))
CONTEXT = DetectorContext(
    organization_id=UUID("22222222-2222-2222-2222-222222222222"),
    window=WINDOW,
    as_of=WINDOW.end,
)


def _stock_reading(scope: str, rate: str, denominator: int) -> MetricReading:
    return MetricReading(
        metric_key="stock_discrepancy_rate",
        metric_version=1,
        query_hash="golden-stock",
        dimensions={"location_id": scope},
        value=Decimal(rate),
        denominator=denominator,
        captured_at=WINDOW.end,
        source_max_timestamp=utc(2026, 8, 1, 22),
    )


def _source_mismatch() -> tuple[Detector, list[MetricReading]]:
    detector = SourceMismatchDetector(
        SourceMismatchConfig(
            rule_id=RULE,
            version=1,
            pack_key="test_pack",
            gap_type="stock_truth_mismatch",
            canonical_entity="fact_stock_count",
            action_playbook_id="test_pack.stock_truth.recount",
        )
    )
    return detector, [
        # Below threshold — must produce nothing. A fixture of only firing cases
        # would not notice a detector that started firing on everything.
        _stock_reading("store-quiet", "0.03", 200),
        # Thin sample above threshold — refused before `detect` sees it.
        _stock_reading("store-thin", "0.60", 5),
        _stock_reading("store-medium", "0.08", 150),
        _stock_reading("store-high", "0.22", 400),
        _stock_reading("store-critical", "0.41", 90),
    ]


def _ratio_threshold() -> tuple[Detector, list[MetricReading]]:
    detector = RatioThresholdDetector(
        RatioThresholdConfig(
            rule_id=RULE,
            version=1,
            pack_key="test_pack",
            gap_type="conversion_below_band",
            metric_name="Conversion rate",
            expected_value=Decimal("0.50"),
            lower_bound=Decimal("0.40"),
            direction=Direction.BELOW,
            exposure_per_unit_minor=Decimal("1250"),
            exposure_denominator_dimension="sessions",
        )
    )
    readings = [
        MetricReading(
            metric_key="conversion_rate",
            metric_version=2,
            query_hash="golden-conversion",
            dimensions={"location_id": scope},
            value=Decimal(value) if value is not None else None,
            denominator=denominator,
            captured_at=WINDOW.end,
        )
        for scope, value, denominator in [
            ("store-inside", "0.46", 600),
            ("store-null", None, 600),
            ("store-below", "0.33", 800),
            ("store-far-below", "0.12", 450),
        ]
    ]
    return detector, readings


def _freshness() -> tuple[Detector, list[MetricReading]]:
    detector = FreshnessDetector(
        FreshnessConfig(
            rule_id=RULE, version=1, pack_key="test_pack", expected_latency_seconds=3600.0
        )
    )
    readings = [
        MetricReading(
            metric_key="source_freshness",
            metric_version=1,
            query_hash="golden-freshness",
            dimensions={"source_key": source},
            value=None,
            denominator=None,
            captured_at=WINDOW.end,
            source_max_timestamp=stamp,
        )
        for source, stamp in [
            ("feed-ontime", utc(2026, 8, 1, 23, 30)),
            ("feed-late", utc(2026, 8, 1, 16)),
            ("feed-very-late", utc(2026, 7, 30)),
            ("feed-never", None),
        ]
    ]
    return detector, readings


def _completeness() -> tuple[Detector, list[MetricReading]]:
    detector = CompletenessDetector(
        CompletenessConfig(rule_id=RULE, version=1, pack_key="test_pack")
    )
    readings = [
        MetricReading(
            metric_key="data_completeness",
            metric_version=1,
            query_hash="golden-completeness",
            dimensions={"source_key": source},
            value=Decimal(value),
            denominator=denominator,
            captured_at=WINDOW.end,
        )
        for source, value, denominator in [
            ("feed-complete", "1.00", 5000),
            ("feed-slightly-short", "0.94", 5000),
            ("feed-broken", "0.41", 5000),
        ]
    ]
    return detector, readings


def _schema_drift() -> tuple[Detector, list[MetricReading]]:
    detector = SchemaDriftDetector(SchemaDriftConfig(rule_id=RULE, version=1, pack_key="test_pack"))
    readings = [
        MetricReading(
            metric_key="schema_drift",
            metric_version=1,
            query_hash="golden-drift",
            dimensions={"source_key": "feed-orders", "drift_kind": kind, "field_name": field},
            value=None,
            denominator=None,
            captured_at=WINDOW.end,
        )
        for kind, field in [
            ("new_field", "loyalty_tier"),
            ("type_change", "order_total"),
            ("removed_field", "store_id"),
        ]
    ]
    # A reading with no drift at all. Without it this fixture fires on
    # everything it is given and could not notice a detector that started
    # raising a gap for every healthy delivery.
    readings.append(
        MetricReading(
            metric_key="schema_drift",
            metric_version=1,
            query_hash="golden-drift",
            dimensions={"source_key": "feed-stable"},
            value=None,
            denominator=None,
            captured_at=WINDOW.end,
        )
    )
    return detector, readings


def _attribution() -> tuple[Detector, list[MetricReading]]:
    detector = AttributionDetector(
        AttributionConfig(
            rule_id=RULE,
            version=1,
            pack_key="test_pack",
            gap_type="campaign_below_baseline",
            canonical_entity="fact_campaign_spend",
            metric_name="Attributable orders per pound",
            attribution_method=AttributionMethod.LAST_TOUCH,
            expected_ratio=Decimal("1.00"),
            threshold_ratio=Decimal("0.80"),
            severity_high_ratio=Decimal("0.50"),
            attributable_share_low=Decimal("0.20"),
            attributable_share_base=Decimal("0.40"),
            attributable_share_high=Decimal("0.70"),
        )
    )
    readings = [
        MetricReading(
            metric_key="attributable_orders_per_pound",
            metric_version=1,
            query_hash="golden-attribution",
            dimensions={"campaign_id": campaign},
            value=Decimal(value),
            denominator=denominator,
            captured_at=WINDOW.end,
        )
        for campaign, value, denominator in [
            ("campaign-healthy", "1.10", 900),
            ("campaign-soft", "0.62", 900),
            ("campaign-poor", "0.28", 1200),
        ]
    ]
    return detector, readings


def _baseline_comparison() -> tuple[Detector, list[MetricReading]]:
    detector = BaselineComparisonDetector(
        BaselineComparisonConfig(
            rule_id=RULE,
            version=1,
            pack_key="test_pack",
            gap_type="conversion_below_baseline",
            canonical_entity="fact_transaction",
            metric_name="Conversion rate",
            minimum_peer_group=5,
        )
    )
    readings = [
        MetricReading(
            metric_key="conversion_rate",
            metric_version=1,
            query_hash="golden-baseline",
            dimensions=(
                {"location_id": scope, "baseline_value": base} if base else {"location_id": scope}
            ),
            value=Decimal(value),
            denominator=denominator,
            captured_at=WINDOW.end,
        )
        for scope, value, base, denominator in [
            ("store-typical-a", "0.30", "0.31", 600),
            ("store-typical-b", "0.29", "0.30", 550),
            ("store-typical-c", "0.31", "0.30", 700),
            ("store-typical-d", "0.30", "0.29", 640),
            ("store-peer-only", "0.14", "", 480),
            ("store-both", "0.09", "0.28", 520),
        ]
    ]
    return detector, readings


def _funnel_drop() -> tuple[Detector, list[MetricReading]]:
    detector = FunnelDropDetector(
        FunnelDropConfig(
            rule_id=RULE,
            version=1,
            pack_key="test_pack",
            gap_type="purchase_funnel_drop",
            canonical_entity="fact_session",
            funnel_name="purchase",
            minimum_observations=0,
            value_per_conversion_minor=Decimal("4500"),
            stages=[
                FunnelStage(key="session", label="Session"),
                FunnelStage(
                    key="product_view",
                    label="Product view",
                    expected_survival=Decimal("0.40"),
                    threshold_survival=Decimal("0.30"),
                ),
                FunnelStage(
                    key="basket",
                    label="Basket",
                    expected_survival=Decimal("0.25"),
                    threshold_survival=Decimal("0.18"),
                ),
                FunnelStage(
                    key="order",
                    label="Order",
                    expected_survival=Decimal("0.70"),
                    threshold_survival=Decimal("0.55"),
                ),
            ],
        )
    )
    readings = [
        MetricReading(
            metric_key="funnel_counts",
            metric_version=1,
            query_hash="golden-funnel",
            dimensions={
                "location_id": scope,
                "session": str(counts[0]),
                "product_view": str(counts[1]),
                "basket": str(counts[2]),
                "order": str(counts[3]),
            },
            value=None,
            denominator=counts[0],
            captured_at=WINDOW.end,
        )
        for scope, counts in [
            ("store-healthy", (10_000, 4200, 1100, 800)),
            ("store-checkout-broken", (10_000, 4200, 1100, 180)),
            ("store-top-of-funnel", (10_000, 2100, 540, 400)),
        ]
    ]
    return detector, readings


def _financial_leakage() -> tuple[Detector, list[MetricReading]]:
    detector = FinancialLeakageDetector(
        FinancialLeakageConfig(
            rule_id=RULE,
            version=1,
            pack_key="test_pack",
            gap_type="margin_leakage",
            canonical_entity="fact_financial_line",
            minimum_observations=30,
        )
    )
    readings = [
        MetricReading(
            metric_key="gross_margin_rate",
            metric_version=1,
            query_hash="golden-leakage",
            dimensions={
                "product_variant_id": scope,
                "margin_rate": margin,
                "prior_margin_rate": prior_margin,
                "revenue_minor": revenue,
                "prior_revenue_minor": prior_revenue,
                "currency": "GBP",
            },
            value=Decimal(margin),
            denominator=800,
            captured_at=WINDOW.end,
        )
        for scope, margin, prior_margin, revenue, prior_revenue in [
            ("variant-steady", "0.355", "0.360", "1000000", "1000000"),
            ("variant-demand-fall", "0.280", "0.360", "600000", "1000000"),
            ("variant-leaking", "0.280", "0.360", "1200000", "1000000"),
            ("variant-cost-creep", "0.330", "0.360", "1000000", "1000000"),
        ]
    ]
    return detector, readings


CASES = {
    "attribution": _attribution,
    "financial_leakage": _financial_leakage,
    "baseline_comparison": _baseline_comparison,
    "funnel_drop": _funnel_drop,
    "source_mismatch": _source_mismatch,
    "ratio_threshold": _ratio_threshold,
    "freshness": _freshness,
    "completeness": _completeness,
    "schema_drift": _schema_drift,
}


def _observed(name: str) -> dict[str, Any]:
    detector, readings = CASES[name]()
    result = detector.run(readings, CONTEXT)
    return {
        "detector": detector.key,
        "config_fingerprint": detector.config.fingerprint(),
        "readings_considered": result.readings_considered,
        "insufficient_readings": result.insufficient_readings,
        "errors": list(result.errors),
        "candidates": [
            {
                "scope_id": c.scope_id,
                "gap_type": c.gap_type,
                "severity": c.severity.value,
                "confidence_band": c.confidence.band.value,
                "confidence_score": c.confidence.score,
                "reason_codes": sorted(c.reason_codes),
                "exposure": (
                    [c.exposure.low_minor, c.exposure.base_minor, c.exposure.high_minor]
                    if c.exposure
                    else None
                ),
                "fingerprint": candidate_fingerprint(c),
            }
            for c in result.candidates
        ],
    }


def test_regeneration_is_refused_on_ci() -> None:
    """A leaked environment variable must not turn this file into a no-op.

    On CI a regenerating golden test reports success no matter what the
    detectors do, and looks exactly like one that is checking. Refusing is the
    only safe default; a genuine regeneration is a local act with a reviewable
    diff.
    """
    if _ON_CI:
        assert not REGENERATE, (
            "FITOS_REGENERATE_GOLDEN is set on CI; these tests would rewrite "
            "their own expectations and pass unconditionally"
        )
    else:
        assert REGENERATE == _REGENERATE_REQUESTED


@pytest.mark.parametrize("name", sorted(CASES))
def test_golden_fixture(name: str) -> None:
    """The recorded output for one detector over a recorded input set.

    Each fixture deliberately mixes firing and non-firing readings. A fixture of
    only firing cases would not notice a detector that started firing on
    everything, which is the more damaging direction: a ledger full of false
    findings is abandoned faster than one that is quietly missing some.
    """
    path = GOLDEN / f"{name}.json"
    observed = _observed(name)

    if REGENERATE:
        path.write_text(json.dumps(observed, indent=2, sort_keys=True) + "\n")
        pytest.skip(f"regenerated {path.name}")

    assert path.exists(), (
        f"{path.name} is missing. Regenerate with FITOS_REGENERATE_GOLDEN=1 and review the diff."
    )
    expected = json.loads(path.read_text())
    assert observed == expected, (
        f"{name} output changed. If the change is intended, regenerate with "
        f"FITOS_REGENERATE_GOLDEN=1 and let the diff be the review."
    )


def test_replay_is_stable_within_a_process() -> None:
    """A golden test over a non-deterministic function proves nothing."""
    for name in CASES:
        assert _observed(name) == _observed(name)


def test_every_fixture_records_at_least_one_non_firing_reading() -> None:
    """The property the fixtures rest on, asserted rather than assumed.

    Without it, a later edit could trim a fixture down to only its firing cases
    and the suite would still pass — while quietly losing the ability to notice a
    detector that fires on everything.
    """
    for name in sorted(CASES):
        _, readings = CASES[name]()
        observed = _observed(name)
        fired = len(observed["candidates"])
        assert fired < len(readings), (
            f"{name} fires on every reading in its fixture; it cannot detect over-firing"
        )
        assert fired > 0, f"{name} fires on nothing; the fixture proves only silence"


def test_the_fixture_set_covers_every_detector_class() -> None:
    """A class added without a fixture has no replay guarantee at all."""
    import importlib
    import pkgutil

    import fitos_worker.detectors as detectors_package

    implemented: set[str] = set()
    for module in pkgutil.iter_modules(detectors_package.__path__):
        loaded = importlib.import_module(f"fitos_worker.detectors.{module.name}")
        for attribute in vars(loaded).values():
            if (
                isinstance(attribute, type)
                and issubclass(attribute, Detector)
                and attribute is not Detector
                and getattr(attribute, "key", None)
            ):
                implemented.add(attribute.key)

    covered = {CASES[name]()[0].key for name in CASES}
    assert implemented <= covered, (
        f"detector classes with no golden fixture: {sorted(implemented - covered)}"
    )
