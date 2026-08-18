"""Dedupe, suppression and correlation.

The headline test is `test_six_consecutive_days_produce_one_evolving_gap` — the
Phase D release gate. Everything else here exists because it is a way that gate
can pass while the behaviour underneath is still wrong.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fitos_worker.detectors.base import (
    DetectorRunResult,
    EvidenceRef,
    GapCandidate,
    ObservationWindow,
    ScopeType,
    Severity,
    Unit,
    utc,
)
from fitos_worker.detectors.confidence import Component, ConfidenceBand, score_confidence
from fitos_worker.detectors.pipeline import (
    SUPPRESSED_REASON_CODE,
    DedupeDecision,
    OpenGap,
    correlate,
    dedupe_key,
    reconcile,
    suppress,
)

ORG = UUID("22222222-2222-2222-2222-222222222222")
RULE = UUID("11111111-1111-1111-1111-111111111111")
OTHER_RULE = UUID("33333333-3333-3333-3333-333333333333")


def window(day: int) -> ObservationWindow:
    return ObservationWindow(start=utc(2026, 8, day), end=utc(2026, 8, day + 1))


def candidate(
    *,
    day: int = 1,
    scope: str = "store-1",
    gap_type: str = "stock_truth_mismatch",
    observed: str = "0.40",
    scope_type: ScopeType = ScopeType.LOCATION,
    correlation_keys: tuple[str, ...] = (),
) -> GapCandidate:
    w = window(day)
    return GapCandidate(
        gap_type=gap_type,
        pack_key="retail_omnichannel",
        scope_type=scope_type,
        scope_id=scope,
        title="t",
        summary="s",
        metric_key="stock_discrepancy_rate",
        metric_version=1,
        observed_value=Decimal(observed),
        expected_value=Decimal("0.02"),
        unit=Unit.RATIO,
        window=w,
        evidence=(
            EvidenceRef(
                canonical_entity="fact_stock_count",
                metric_key="stock_discrepancy_rate",
                metric_version=1,
                query_hash=f"hash-day-{day}",
                observation_window=w.to_json(),
                captured_at=w.end,
            ),
        ),
        severity=Severity.MEDIUM,
        confidence=score_confidence({Component.SAMPLE_SIZE: 0.9}),
        correlation_keys=correlation_keys,
    )


def run(*candidates: GapCandidate, rule_id: UUID = RULE) -> DetectorRunResult:
    return DetectorRunResult(
        detector_key="source_mismatch",
        rule_id=rule_id,
        rule_version=1,
        config_fingerprint="fp",
        window=candidates[0].window if candidates else window(1),
        readings_considered=len(candidates),
        candidates=candidates,
        insufficient_readings=0,
    )


# --- the release gate -------------------------------------------------------


def test_six_consecutive_days_produce_one_evolving_gap() -> None:
    """The Phase D dedupe release gate.

    Scenario 2: the same stock discrepancy at the same location on six
    consecutive days. One evolving gap with a timeline, not six rows. Getting
    this wrong is not subtle in production — it is a ledger nobody can work.
    """
    open_gaps: list[OpenGap] = []
    created = 0
    updated = 0

    for day in range(1, 7):
        result = reconcile([run(candidate(day=day))], organization_id=ORG, open_gaps=open_gaps)
        assert len(result.outcomes) == 1
        outcome = result.outcomes[0]

        if outcome.decision is DedupeDecision.CREATE:
            created += 1
            open_gaps.append(
                OpenGap(
                    gap_id=uuid4(),
                    dedupe_key=outcome.dedupe_key,
                    gap_type=outcome.candidate.gap_type,
                    scope_type=outcome.candidate.scope_type.value,
                    scope_id=outcome.candidate.scope_id,
                    status="detected",
                )
            )
        else:
            updated += 1

    assert created == 1, "six days produced more than one gap"
    assert updated == 5, "days two to six should have updated the existing gap"


def test_the_dedupe_key_excludes_the_window() -> None:
    """The exclusion *is* the gate. Including the window is the natural thing to
    write and produces one row per day."""
    monday = dedupe_key(candidate(day=1), organization_id=ORG, rule_id=RULE)
    tuesday = dedupe_key(candidate(day=2), organization_id=ORG, rule_id=RULE)
    assert monday == tuesday


def test_the_dedupe_key_excludes_the_values() -> None:
    """A discrepancy that worsens from 40% to 60% is the same gap getting worse,
    not a second gap."""
    mild = dedupe_key(candidate(observed="0.40"), organization_id=ORG, rule_id=RULE)
    severe = dedupe_key(candidate(observed="0.60"), organization_id=ORG, rule_id=RULE)
    assert mild == severe


def test_the_dedupe_key_separates_distinct_scopes() -> None:
    base = dedupe_key(candidate(), organization_id=ORG, rule_id=RULE)
    other = dedupe_key(candidate(scope="store-2"), organization_id=ORG, rule_id=RULE)
    assert base != other


def test_the_dedupe_key_separates_distinct_gap_types() -> None:
    base = dedupe_key(candidate(), organization_id=ORG, rule_id=RULE)
    other = dedupe_key(
        candidate(gap_type="conversion_below_band"), organization_id=ORG, rule_id=RULE
    )
    assert base != other


def test_the_dedupe_key_separates_organizations() -> None:
    """The single most important separation in the system."""
    ours = dedupe_key(candidate(), organization_id=ORG, rule_id=RULE)
    theirs = dedupe_key(candidate(), organization_id=uuid4(), rule_id=RULE)
    assert ours != theirs


def test_the_dedupe_key_separates_rules() -> None:
    """Two rules finding the same scope are two findings; a reader needs to see
    both, and merging them would hide one rule's opinion behind the other's."""
    assert dedupe_key(candidate(), organization_id=ORG, rule_id=RULE) != dedupe_key(
        candidate(), organization_id=ORG, rule_id=OTHER_RULE
    )


def test_the_dedupe_key_separates_scope_types() -> None:
    """A location called "north" and a channel called "north" are not the same
    scope, and a key built from the id alone would merge them."""
    location = dedupe_key(
        candidate(scope="north", scope_type=ScopeType.LOCATION),
        organization_id=ORG,
        rule_id=RULE,
    )
    channel = dedupe_key(
        candidate(scope="north", scope_type=ScopeType.CHANNEL),
        organization_id=ORG,
        rule_id=RULE,
    )
    assert location != channel


# --- terminal gaps ----------------------------------------------------------


@pytest.mark.parametrize("status", ["resolved", "dismissed"])
def test_a_terminal_gap_does_not_absorb_a_new_finding(status: str) -> None:
    """The same condition recurring after somebody closed it is a new finding.
    Absorbing it would resurrect closed work into somebody's queue."""
    key = dedupe_key(candidate(), organization_id=ORG, rule_id=RULE)
    closed = OpenGap(
        gap_id=uuid4(),
        dedupe_key=key,
        gap_type="stock_truth_mismatch",
        scope_type="location",
        scope_id="store-1",
        status=status,
    )
    result = reconcile([run(candidate(day=4))], organization_id=ORG, open_gaps=[closed])

    assert result.outcomes[0].decision is DedupeDecision.CREATE
    assert result.outcomes[0].existing_gap_id is None


@pytest.mark.parametrize(
    "status", ["detected", "triaged", "investigating", "actioned", "validating"]
)
def test_a_non_terminal_gap_is_updated_whatever_its_status(status: str) -> None:
    """A detector re-firing on an actioned gap appends to its timeline. It does
    not reopen it — reopening is an explicit human action."""
    key = dedupe_key(candidate(), organization_id=ORG, rule_id=RULE)
    existing_id = uuid4()
    open_gap = OpenGap(
        gap_id=existing_id,
        dedupe_key=key,
        gap_type="stock_truth_mismatch",
        scope_type="location",
        scope_id="store-1",
        status=status,
    )
    result = reconcile([run(candidate(day=4))], organization_id=ORG, open_gaps=[open_gap])

    assert result.outcomes[0].decision is DedupeDecision.UPDATE
    assert result.outcomes[0].existing_gap_id == existing_id


def test_two_candidates_colliding_within_one_run_do_not_both_create() -> None:
    """The partial unique index would refuse the second INSERT. Better to
    reconcile it here than to fail a run that had already done its work."""
    result = reconcile(
        [run(candidate(day=1), candidate(day=1, observed="0.55"))],
        organization_id=ORG,
    )
    assert len(result.creates) == 1
    assert len(result.updates) == 1


# --- suppression ------------------------------------------------------------


def _quality_gap(scope: str = "store-1", sources: frozenset[str] = frozenset()) -> OpenGap:
    return OpenGap(
        gap_id=uuid4(),
        dedupe_key="dq",
        gap_type="source_freshness_breach",
        scope_type="location",
        scope_id=scope,
        status="triaged",
        contributing_sources=sources,
    )


def test_a_suppressed_candidate_is_marked_not_hidden() -> None:
    """Hiding it would make a data outage look like calm, which is the most
    expensive possible way to be wrong."""
    kept, suppressed = suppress([candidate()], open_gaps=[_quality_gap()])

    assert len(kept) == 1, "suppression must never drop a candidate"
    assert SUPPRESSED_REASON_CODE in kept[0].reason_codes
    assert suppressed == ["stock_truth_mismatch:store-1"]


def test_a_suppressed_candidate_has_its_confidence_capped() -> None:
    kept, _ = suppress([candidate()], open_gaps=[_quality_gap()])

    assert kept[0].confidence.band is ConfidenceBand.LOW
    assert SUPPRESSED_REASON_CODE in kept[0].confidence.reason_codes


def test_an_unaffected_candidate_is_untouched() -> None:
    kept, suppressed = suppress([candidate()], open_gaps=[_quality_gap(scope="store-9")])

    assert suppressed == []
    assert kept[0].reason_codes == ()
    assert kept[0].confidence.band is ConfidenceBand.HIGH


def test_a_resolved_quality_gap_stops_suppressing() -> None:
    resolved = OpenGap(
        gap_id=uuid4(),
        dedupe_key="dq",
        gap_type="source_freshness_breach",
        scope_type="location",
        scope_id="store-1",
        status="resolved",
    )
    _, suppressed = suppress([candidate()], open_gaps=[resolved])
    assert suppressed == []


def test_a_data_quality_gap_is_not_suppressed_by_another_one() -> None:
    """Silencing the outage report during the outage."""
    dq_candidate = candidate(gap_type="data_completeness_drop")
    kept, suppressed = suppress([dq_candidate], open_gaps=[_quality_gap()])

    assert suppressed == []
    assert kept[0].reason_codes == ()


def test_suppression_follows_a_shared_source_not_just_a_shared_scope() -> None:
    """A freshness gap on the footfall feed suppresses a conversion gap that
    depends on it, even though they are scoped differently."""
    upstream = _quality_gap(scope="feed-footfall", sources=frozenset({"metric:footfall@v1"}))
    downstream = candidate(
        scope="store-7",
        gap_type="conversion_below_band",
        correlation_keys=("metric:footfall@v1",),
    )
    kept, suppressed = suppress([downstream], open_gaps=[upstream])

    assert SUPPRESSED_REASON_CODE in kept[0].reason_codes
    assert suppressed == ["conversion_below_band:store-7"]


def test_suppression_preserves_order_and_length() -> None:
    """`reconcile` matches each candidate to its detector by position. This
    guarantee is what makes that safe, and it is asserted rather than assumed."""
    candidates = [
        candidate(scope="store-1"),
        candidate(scope="store-2", gap_type="conversion_below_band"),
        candidate(scope="store-3"),
    ]
    kept, _ = suppress(candidates, open_gaps=[_quality_gap(scope="store-2")])

    assert len(kept) == 3
    assert [c.scope_id for c in kept] == ["store-1", "store-2", "store-3"]


def test_the_run_record_counts_suppressions() -> None:
    """Suppression is auditable rather than invisible."""
    result = reconcile(
        [run(candidate(), candidate(scope="store-9"))],
        organization_id=ORG,
        open_gaps=[_quality_gap()],
    )
    record = result.to_record()

    assert record["candidates_produced"] == 2
    assert record["candidates_suppressed"] == 1
    assert len(record["dedupe_decisions"]) == 2  # type: ignore[arg-type]


# --- correlation ------------------------------------------------------------


def test_related_gaps_are_linked_not_merged() -> None:
    """Merging would lose the distinct metric definitions, and "these are
    connected" is a different claim from "these are one thing"."""
    freshness = candidate(
        scope="store-1",
        gap_type="source_freshness_breach",
        correlation_keys=("metric:footfall@v1",),
    )
    conversion = candidate(
        scope="store-1",
        gap_type="conversion_below_band",
        correlation_keys=("metric:footfall@v1",),
    )
    result = reconcile([run(freshness, conversion)], organization_id=ORG)

    assert len(result.creates) + len(result.updates) == 2, "neither gap was merged away"
    assert result.correlations == (
        ("conversion_below_band:store-1", "source_freshness_breach:store-1"),
    )


def test_unrelated_gaps_are_not_linked() -> None:
    left = candidate(scope="store-1", correlation_keys=("metric:a@v1",))
    right = candidate(
        scope="store-2", gap_type="conversion_below_band", correlation_keys=("metric:b@v1",)
    )
    assert correlate([left, right]) == []


def test_the_same_finding_in_the_same_scope_is_not_correlated_with_itself() -> None:
    assert correlate([candidate(), candidate()]) == []


def test_correlation_pairs_are_stable_ordered() -> None:
    """A replay must produce the same graph, so a fixture over it means
    something."""
    a = candidate(scope="store-1", gap_type="a", correlation_keys=("m",))
    b = candidate(scope="store-1", gap_type="b", correlation_keys=("m",))
    assert correlate([a, b]) == correlate([b, a])


def test_gaps_in_different_windows_do_not_correlate_by_scope_alone() -> None:
    """Same store, different days is a timeline, not a correlation."""
    monday = candidate(day=1, gap_type="a")
    friday = candidate(day=5, gap_type="b")
    assert correlate([monday, friday]) == []


# --- the empty case ---------------------------------------------------------


def test_a_run_with_no_candidates_reconciles_cleanly() -> None:
    result = reconcile([run()], organization_id=ORG)

    assert result.outcomes == ()
    assert result.correlations == ()
    assert result.to_record()["candidates_produced"] == 0


def test_reconcile_over_multiple_detectors_keeps_their_rules_apart() -> None:
    """The candidates are rebuilt during suppression, so the detector each one
    came from is tracked positionally. If that alignment slipped, these two
    would collide onto one key."""
    first = run(candidate(scope="store-1"), rule_id=RULE)
    second = run(candidate(scope="store-1"), rule_id=OTHER_RULE)
    result = reconcile([first, second], organization_id=ORG, open_gaps=[_quality_gap()])

    keys = {o.dedupe_key for o in result.outcomes}
    assert len(keys) == 2, "two rules must not share a dedupe key"


def test_reconcile_alignment_survives_suppression_rebuilding_candidates() -> None:
    """The specific regression: matching candidates to detectors by identity
    breaks the moment suppression replaces one, because `replace()` returns a
    new object."""
    first = run(candidate(scope="store-1"), rule_id=RULE)
    second = run(candidate(scope="store-2"), rule_id=OTHER_RULE)
    # store-1 is suppressed and rebuilt; store-2 is not.
    result = reconcile([first, second], organization_id=ORG, open_gaps=[_quality_gap()])

    by_scope = {o.candidate.scope_id: o.dedupe_key for o in result.outcomes}
    assert by_scope["store-1"] == dedupe_key(
        result.outcomes[0].candidate, organization_id=ORG, rule_id=RULE
    )
    assert by_scope["store-2"] == dedupe_key(
        candidate(scope="store-2"), organization_id=ORG, rule_id=OTHER_RULE
    )


def test_a_timeline_entry_carries_the_days_own_query_hash() -> None:
    """One gap across six days still needs six resolvable evidence references —
    otherwise the timeline is a story with no receipts."""
    hashes: set[str] = set()
    for day in range(1, 7):
        result = reconcile([run(candidate(day=day))], organization_id=ORG)
        hashes.update(ref.query_hash for ref in result.outcomes[0].candidate.evidence)
    assert len(hashes) == 6


def test_the_window_advances_while_the_key_holds() -> None:
    monday = reconcile([run(candidate(day=1))], organization_id=ORG).outcomes[0]
    saturday = reconcile([run(candidate(day=6))], organization_id=ORG).outcomes[0]

    assert monday.dedupe_key == saturday.dedupe_key
    assert saturday.candidate.window.as_of - monday.candidate.window.as_of == timedelta(days=5)
