"""Baseline comparison and funnel drop.

Both classes exist to answer "compared to what", and both fail in the same way
if the comparison basis is wrong rather than absent — a peer group of two, a
mean dragged by a flagship, a funnel step nobody set a threshold on. The tests
here are mostly about those.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from fitos_worker.detectors.base import (
    DetectorContext,
    MetricReading,
    ObservationWindow,
    Severity,
    Unit,
    utc,
)
from fitos_worker.detectors.baseline_comparison import (
    BaselineComparisonConfig,
    BaselineComparisonDetector,
    ComparisonBasis,
)
from fitos_worker.detectors.funnel_drop import (
    FunnelDropConfig,
    FunnelDropDetector,
    FunnelStage,
)

RULE = UUID("11111111-1111-1111-1111-111111111111")
WINDOW = ObservationWindow(start=utc(2026, 8, 1), end=utc(2026, 8, 8))
CONTEXT = DetectorContext(
    organization_id=UUID("22222222-2222-2222-2222-222222222222"),
    window=WINDOW,
    as_of=WINDOW.end,
)


# ---------------------------------------------------------------------------
# Baseline comparison
# ---------------------------------------------------------------------------


def conv(
    scope: str, value: str, *, baseline: str | None = None, denominator: int = 400
) -> MetricReading:
    dims = {"location_id": scope}
    if baseline is not None:
        dims["baseline_value"] = baseline
    return MetricReading(
        metric_key="conversion_rate",
        metric_version=1,
        query_hash="baseline",
        dimensions=dims,
        value=Decimal(value),
        denominator=denominator,
        captured_at=WINDOW.end,
    )


def baseline(**overrides: object) -> BaselineComparisonDetector:
    config: dict[str, object] = {
        "rule_id": RULE,
        "version": 1,
        "pack_key": "test_pack",
        "gap_type": "conversion_below_baseline",
        "canonical_entity": "fact_transaction",
        "metric_name": "Conversion rate",
    }
    config.update(overrides)
    return BaselineComparisonDetector(BaselineComparisonConfig(**config))  # type: ignore[arg-type]


def _peers(*values: str) -> list[MetricReading]:
    return [conv(f"store-{i}", v) for i, v in enumerate(values)]


def test_a_scope_below_its_own_baseline_fires() -> None:
    result = baseline(basis=ComparisonBasis.OWN_BASELINE).run(
        [conv("store-1", "0.15", baseline="0.24")], CONTEXT
    )
    candidate = result.candidates[0]
    assert candidate.expected_value == Decimal("0.24")
    assert "below_own_baseline" in candidate.reason_codes


def test_a_scope_at_its_baseline_is_silent() -> None:
    assert (
        baseline(basis=ComparisonBasis.OWN_BASELINE)
        .run([conv("store-1", "0.23", baseline="0.24")], CONTEXT)
        .candidates
        == ()
    )


def test_a_scope_with_no_baseline_is_not_compared_against_zero() -> None:
    """A missing baseline is an absent comparison, not a baseline of nothing."""
    assert (
        baseline(basis=ComparisonBasis.OWN_BASELINE)
        .run([conv("store-1", "0.15")], CONTEXT)
        .candidates
        == ()
    )


def test_a_peer_group_below_the_minimum_is_refused() -> None:
    """A peer group of two is not a peer group. This is a refusal to compare,
    not a caveat on the comparison."""
    readings = _peers("0.30", "0.30", "0.05")
    assert (
        baseline(basis=ComparisonBasis.PEER_GROUP, minimum_peer_group=5)
        .run(readings, CONTEXT)
        .candidates
        == ()
    )


def test_a_sufficient_peer_group_produces_a_comparison() -> None:
    readings = _peers("0.30", "0.31", "0.29", "0.30", "0.10")
    result = baseline(basis=ComparisonBasis.PEER_GROUP, minimum_peer_group=5).run(readings, CONTEXT)
    assert [c.scope_id for c in result.candidates] == ["store-4"]
    assert "below_peer_group" in result.candidates[0].reason_codes


def test_peers_are_compared_against_the_median_not_the_mean() -> None:
    """One flagship drags a mean upward and reports every ordinary store as
    underperforming — a detector firing on the shape of the estate."""
    # Mean is ~0.35; median is 0.20. Ordinary stores at 0.19 are fine against
    # the median and 46% below the mean.
    readings = _peers("0.20", "0.19", "0.20", "0.21", "0.20", "1.20")
    result = baseline(basis=ComparisonBasis.PEER_GROUP, minimum_peer_group=5).run(readings, CONTEXT)
    assert result.candidates == (), "the flagship must not make every store a gap"


def test_a_scope_below_both_bases_is_one_finding_not_two() -> None:
    """Two rows for one store's one problem is the ledger failure dedupe exists
    to prevent, arriving through a different door."""
    readings = [
        conv("store-0", "0.30"),
        conv("store-1", "0.31"),
        conv("store-2", "0.29"),
        conv("store-3", "0.30"),
        conv("store-4", "0.10", baseline="0.28"),
    ]
    result = baseline(minimum_peer_group=5).run(readings, CONTEXT)

    for_store_4 = [c for c in result.candidates if c.scope_id == "store-4"]
    assert len(for_store_4) == 1
    assert set(for_store_4[0].reason_codes) == {"below_own_baseline", "below_peer_group"}
    assert "and" in for_store_4[0].summary, "both comparisons are named"


def test_agreeing_comparisons_fit_the_question_better() -> None:
    """Held against the same peer group, so only the number of comparisons varies.

    The first version of this test compared "both bases" against "own baseline
    alone" and failed: adding a peer comparison over a five-store group pulls
    `source_agreement` down far enough to lower the total. That is the
    arithmetic being right and the claim being wrong — "two comparisons agree"
    and "both comparisons are well founded" are different statements, and only
    the second is about confidence.
    """
    peers = [conv(f"store-{i}", "0.30") for i in range(4)]
    both = baseline(minimum_peer_group=5).run(
        [*peers, conv("store-4", "0.10", baseline="0.28")], CONTEXT
    )
    peer_only = baseline(basis=ComparisonBasis.PEER_GROUP, minimum_peer_group=5).run(
        [*peers, conv("store-4", "0.10", baseline="0.28")], CONTEXT
    )

    two = both.candidates[-1]
    one = peer_only.candidates[-1]
    assert two.confidence.components["detector_fit"] > one.confidence.components["detector_fit"]
    assert two.confidence.score > one.confidence.score


def test_a_thin_peer_group_can_lower_the_total_even_with_two_comparisons() -> None:
    """The property the previous test does *not* claim, stated so nobody
    re-derives the wrong one: a badly founded comparison is not free."""
    peers = [conv(f"store-{i}", "0.30") for i in range(4)]
    thin = (
        baseline(minimum_peer_group=5)
        .run([*peers, conv("store-4", "0.10", baseline="0.28")], CONTEXT)
        .candidates[-1]
    )
    baseline_only = (
        baseline(basis=ComparisonBasis.OWN_BASELINE)
        .run([conv("store-4", "0.10", baseline="0.28")], CONTEXT)
        .candidates[0]
    )

    assert thin.confidence.score < baseline_only.confidence.score
    assert "source_agreement" in thin.confidence.components
    assert "source_agreement" in baseline_only.confidence.dropped


def test_a_thin_peer_group_lowers_the_confidence() -> None:
    """A group scraping past the floor must not read as a confident comparison."""
    small = baseline(basis=ComparisonBasis.PEER_GROUP, minimum_peer_group=5).run(
        _peers("0.30", "0.30", "0.30", "0.30", "0.05"), CONTEXT
    )
    large = baseline(basis=ComparisonBasis.PEER_GROUP, minimum_peer_group=5).run(
        [*[conv(f"store-{i}", "0.30") for i in range(19)], conv("store-19", "0.05")], CONTEXT
    )
    assert small.candidates[0].confidence.score < large.candidates[0].confidence.score


@pytest.mark.parametrize(
    ("value", "expected"),
    [("0.22", Severity.MEDIUM), ("0.18", Severity.HIGH), ("0.10", Severity.CRITICAL)],
)
def test_baseline_severity_steps_with_the_shortfall(value: str, expected: Severity) -> None:
    candidate = (
        baseline(basis=ComparisonBasis.OWN_BASELINE)
        .run([conv("store-1", value, baseline="0.28")], CONTEXT)
        .candidates[0]
    )
    assert candidate.severity is expected


def test_the_baseline_copy_claims_no_cause() -> None:
    candidate = (
        baseline(basis=ComparisonBasis.OWN_BASELINE)
        .run([conv("store-1", "0.10", baseline="0.28")], CONTEXT)
        .candidates[0]
    )
    assert "comparisons, not" in candidate.summary
    for word in ("because", "caused", "due to"):
        assert word not in candidate.summary.lower()


def test_out_of_order_severity_thresholds_are_refused() -> None:
    with pytest.raises(ValueError, match="must increase"):
        BaselineComparisonConfig(
            rule_id=RULE,
            version=1,
            pack_key="p",
            gap_type="g",
            canonical_entity="e",
            metric_name="m",
            threshold_shortfall=Decimal("0.50"),
            severity_high_shortfall=Decimal("0.30"),
            severity_critical_shortfall=Decimal("0.20"),
        )


def test_a_baseline_gap_carries_no_exposure() -> None:
    """Being below a peer median is not money."""
    candidate = (
        baseline(basis=ComparisonBasis.OWN_BASELINE)
        .run([conv("store-1", "0.10", baseline="0.28")], CONTEXT)
        .candidates[0]
    )
    assert candidate.exposure is None


# ---------------------------------------------------------------------------
# Funnel drop
# ---------------------------------------------------------------------------


STAGES = [
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
]


def funnel_reading(scope: str = "store-1", **counts: int) -> MetricReading:
    return MetricReading(
        metric_key="funnel_counts",
        metric_version=1,
        query_hash="funnel",
        dimensions={"location_id": scope, **{k: str(v) for k, v in counts.items()}},
        value=None,
        denominator=counts.get("session"),
        captured_at=WINDOW.end,
    )


def funnel(**overrides: object) -> FunnelDropDetector:
    config: dict[str, object] = {
        "rule_id": RULE,
        "version": 1,
        "pack_key": "test_pack",
        "gap_type": "purchase_funnel_drop",
        "canonical_entity": "fact_session",
        "funnel_name": "purchase",
        "stages": STAGES,
        "minimum_observations": 0,
    }
    config.update(overrides)
    return FunnelDropDetector(FunnelDropConfig(**config))  # type: ignore[arg-type]


def test_a_healthy_funnel_is_silent() -> None:
    healthy = funnel_reading(session=10_000, product_view=4200, basket=1100, order=780)
    assert funnel().run([healthy], CONTEXT).candidates == ()


def test_the_worst_step_is_reported_not_the_worst_total() -> None:
    """ "2% overall conversion" is true and unactionable. "84% of people who
    reached the basket did not check out" is where to look."""
    broken = funnel_reading(session=10_000, product_view=4200, basket=1100, order=180)
    candidate = funnel().run([broken], CONTEXT).candidates[0]

    assert "Order" in candidate.title
    assert "stage_order" in candidate.reason_codes
    assert candidate.observed_value == pytest.approx(Decimal("180") / Decimal("1100"))


def test_only_one_candidate_per_funnel() -> None:
    """A funnel that is bad at three steps is one finding about a funnel."""
    bad = funnel_reading(session=10_000, product_view=2000, basket=200, order=60)
    assert len(funnel().run([bad], CONTEXT).candidates) == 1


def test_thresholds_are_per_step() -> None:
    """A 60% drop from session to product view is normal; the same drop from
    payment details to order is a broken checkout."""
    # 42% survive into product view (fine), 26% into basket (fine), 30% into
    # order (below its 55% threshold).
    reading = funnel_reading(session=10_000, product_view=4200, basket=1100, order=330)
    candidate = funnel().run([reading], CONTEXT).candidates[0]
    assert "stage_order" in candidate.reason_codes


def test_an_increasing_stage_is_refused_not_reported_as_a_negative_drop() -> None:
    """A negative drop-off renders as a suspiciously good number, and nobody
    investigates those."""
    impossible = funnel_reading(session=1000, product_view=400, basket=900, order=100)
    result = funnel().run([impossible], CONTEXT)

    assert result.candidates == ()
    assert not result.succeeded
    assert "non-increasing" in result.errors[0]


def test_an_incomplete_funnel_is_not_a_small_funnel() -> None:
    """Reporting a drop to a stage that was never measured would invent one."""
    partial = funnel_reading(session=1000, product_view=400)
    assert funnel().run([partial], CONTEXT).candidates == ()


def test_an_empty_funnel_produces_nothing() -> None:
    empty = funnel_reading(session=0, product_view=0, basket=0, order=0)
    assert funnel().run([empty], CONTEXT).candidates == ()


def test_a_stage_with_no_threshold_is_refused_at_config_time() -> None:
    """A stage the detector silently never checks looks identical to one that is
    always healthy."""
    with pytest.raises(ValueError, match="would never fire"):
        FunnelDropConfig(
            rule_id=RULE,
            version=1,
            pack_key="p",
            gap_type="g",
            canonical_entity="e",
            funnel_name="f",
            stages=[
                FunnelStage(key="a", label="A"),
                FunnelStage(key="b", label="B", threshold_survival=Decimal("0.5")),
                FunnelStage(key="c", label="C"),
            ],
        )


def test_a_threshold_on_the_first_stage_is_refused() -> None:
    with pytest.raises(ValueError, match="no predecessor"):
        FunnelDropConfig(
            rule_id=RULE,
            version=1,
            pack_key="p",
            gap_type="g",
            canonical_entity="e",
            funnel_name="f",
            stages=[
                FunnelStage(key="a", label="A", threshold_survival=Decimal("0.5")),
                FunnelStage(key="b", label="B", threshold_survival=Decimal("0.5")),
            ],
        )


def test_a_threshold_above_its_expected_survival_is_refused() -> None:
    """It would fire on every healthy funnel."""
    with pytest.raises(ValueError, match="would always fire"):
        FunnelStage(
            key="b",
            label="B",
            expected_survival=Decimal("0.40"),
            threshold_survival=Decimal("0.60"),
        )


def test_duplicate_stage_keys_are_refused() -> None:
    with pytest.raises(ValueError, match="duplicate stage keys"):
        FunnelDropConfig(
            rule_id=RULE,
            version=1,
            pack_key="p",
            gap_type="g",
            canonical_entity="e",
            funnel_name="f",
            stages=[
                FunnelStage(key="a", label="A"),
                FunnelStage(key="a", label="Also A", threshold_survival=Decimal("0.5")),
            ],
        )


def test_a_funnel_gap_carries_no_exposure_by_default() -> None:
    """A drop-off is not money until somebody says what a conversion is worth."""
    broken = funnel_reading(session=10_000, product_view=4200, basket=1100, order=180)
    assert funnel().run([broken], CONTEXT).candidates[0].exposure is None


def test_a_declared_conversion_value_produces_an_exposure() -> None:
    broken = funnel_reading(session=10_000, product_view=4200, basket=1100, order=180)
    candidate = (
        funnel(value_per_conversion_minor=Decimal("4500")).run([broken], CONTEXT).candidates[0]
    )

    exposure = candidate.exposure
    assert exposure is not None
    # 70% of 1100 expected is 770; 180 arrived, so 590 short.
    assert exposure.base_minor == 590 * 4500
    assert exposure.currency == "GBP"


def test_the_funnel_copy_locates_the_step_without_explaining_it() -> None:
    broken = funnel_reading(session=10_000, product_view=4200, basket=1100, order=180)
    candidate = funnel().run([broken], CONTEXT).candidates[0]

    assert "did not continue" in candidate.summary
    assert "locates the step; it does not establish why" in candidate.summary


@pytest.mark.parametrize(
    ("order_count", "expected"),
    [(560, Severity.MEDIUM), (440, Severity.HIGH), (180, Severity.CRITICAL)],
)
def test_funnel_severity_steps_with_the_shortfall(order_count: int, expected: Severity) -> None:
    reading = funnel_reading(session=10_000, product_view=4200, basket=1100, order=order_count)
    assert funnel().run([reading], CONTEXT).candidates[0].severity is expected


def test_the_funnel_unit_is_a_ratio() -> None:
    broken = funnel_reading(session=10_000, product_view=4200, basket=1100, order=180)
    assert funnel().run([broken], CONTEXT).candidates[0].unit is Unit.RATIO
