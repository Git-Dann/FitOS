"""Dedupe, suppression and correlation.

Runs once over every detector's candidates, never inside a detector. Twelve
detectors that each dedupe for themselves dedupe twelve slightly different ways,
and the ledger fills with near-duplicates that are individually defensible.

The three stages, each from gap-model.md §6:

**Dedupe.** The key is `hash(organization_id, pack_key, gap_type, scope_type,
scope_id, rule_id)` — deliberately *excluding* the observation window and the
values. That exclusion is the release gate for this phase: the same stock
discrepancy on six consecutive days must be one evolving gap with a timeline,
not six rows. Including the window is the natural thing to write and produces a
ledger nobody can work.

**Suppression.** A gap whose contributing source has an open freshness or
completeness problem is *not hidden*. It is created with reason code
`suppressed_by_data_quality`, a capped confidence band and a link to the
data-quality gap. Hiding it would make a data outage look like calm, which is
the most expensive possible way to be wrong.

**Correlation.** Related gaps are linked and shown, never merged. Merging loses
the distinct metric definitions, and "these two things are connected" is a
different claim from "these two things are one thing".
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from uuid import UUID

from fitos_worker.detectors.base import (
    DetectorRunResult,
    GapCandidate,
)
from fitos_worker.detectors.confidence import ConfidenceBand

# Gap types that describe the data itself rather than the business. An open gap
# of one of these kinds suppresses business gaps that depend on the same source.
DATA_QUALITY_GAP_TYPES = frozenset(
    {
        "source_freshness_breach",
        "data_completeness_drop",
        "schema_drift",
        "identity_match_failure",
    }
)

SUPPRESSED_REASON_CODE = "suppressed_by_data_quality"


class DedupeDecision(StrEnum):
    CREATE = "create"
    UPDATE = "update"


@dataclass(frozen=True)
class OpenGap:
    """The minimum the pipeline needs to know about a gap already in the ledger.

    Deliberately not the whole aggregate: the pipeline must not be able to read
    or write fields it has no business touching, and `status` and `owner_id` in
    particular are human state that a detector re-firing must leave alone.
    """

    gap_id: UUID
    dedupe_key: str
    gap_type: str
    scope_type: str
    scope_id: str
    status: str
    contributing_sources: frozenset[str] = frozenset()


@dataclass(frozen=True)
class DedupeOutcome:
    """One candidate's fate, recorded so suppression is auditable rather than invisible."""

    dedupe_key: str
    decision: DedupeDecision
    existing_gap_id: UUID | None
    candidate: GapCandidate


@dataclass(frozen=True)
class PipelineResult:
    outcomes: tuple[DedupeOutcome, ...]
    suppressed: tuple[str, ...]
    correlations: tuple[tuple[str, str], ...]

    @property
    def creates(self) -> tuple[DedupeOutcome, ...]:
        return tuple(o for o in self.outcomes if o.decision is DedupeDecision.CREATE)

    @property
    def updates(self) -> tuple[DedupeOutcome, ...]:
        return tuple(o for o in self.outcomes if o.decision is DedupeDecision.UPDATE)

    def to_record(self) -> dict[str, object]:
        return {
            "candidates_produced": len(self.outcomes),
            "candidates_suppressed": len(self.suppressed),
            "dedupe_created": len(self.creates),
            "dedupe_updated": len(self.updates),
            "correlations_linked": len(self.correlations),
            "dedupe_decisions": [
                {
                    "dedupe_key": o.dedupe_key,
                    "decision": o.decision.value,
                    "existing_gap_id": str(o.existing_gap_id) if o.existing_gap_id else None,
                }
                for o in self.outcomes
            ],
        }


def dedupe_key(candidate: GapCandidate, *, organization_id: UUID, rule_id: UUID) -> str:
    """Stable across windows and values, by construction.

    Hashed rather than stored raw because `scope_id` can be a long external
    identifier and the column is indexed; the material is reconstructible from
    the gap's own fields, so nothing is lost.
    """
    material = candidate.dedupe_key_material(organization_id, rule_id)
    return hashlib.sha256(material.encode()).hexdigest()


def _is_terminal(status: str) -> bool:
    return status in {"resolved", "dismissed"}


def suppress(
    candidates: Sequence[GapCandidate],
    *,
    open_gaps: Iterable[OpenGap],
) -> tuple[list[GapCandidate], list[str]]:
    """Mark candidates whose inputs are themselves in question.

    Returns every candidate, in the input order — none are dropped and none are
    reordered. Callers rely on that alignment to keep each candidate matched to
    the detector that produced it, and `test_suppression_preserves_order_and_length`
    holds the guarantee in place. The suppressed ones carry the reason code and a
    confidence band capped at `low`, so the ledger shows a finding the reader can
    immediately see is standing on soft ground.
    """
    quality_scopes = {
        (gap.scope_type, gap.scope_id)
        for gap in open_gaps
        if gap.gap_type in DATA_QUALITY_GAP_TYPES and not _is_terminal(gap.status)
    }
    quality_sources = {
        source
        for gap in open_gaps
        if gap.gap_type in DATA_QUALITY_GAP_TYPES and not _is_terminal(gap.status)
        for source in gap.contributing_sources
    }

    kept: list[GapCandidate] = []
    suppressed: list[str] = []
    for candidate in candidates:
        if candidate.gap_type in DATA_QUALITY_GAP_TYPES:
            # A data-quality gap is not suppressed by another one. Doing so
            # would silence the outage report during the outage.
            kept.append(candidate)
            continue

        scope_hit = (candidate.scope_type.value, candidate.scope_id) in quality_scopes
        source_hit = bool(quality_sources & set(candidate.correlation_keys))
        if not (scope_hit or source_hit):
            kept.append(candidate)
            continue

        capped = replace(
            candidate,
            confidence=replace(
                candidate.confidence,
                band=ConfidenceBand.LOW,
                reason_codes=(*candidate.confidence.reason_codes, SUPPRESSED_REASON_CODE),
                caps_applied=(*candidate.confidence.caps_applied, "data quality"),
            ),
            reason_codes=(*candidate.reason_codes, SUPPRESSED_REASON_CODE),
        )
        kept.append(capped)
        suppressed.append(f"{capped.gap_type}:{capped.scope_id}")

    return kept, suppressed


def correlate(candidates: Sequence[GapCandidate]) -> list[tuple[str, str]]:
    """Link candidates sharing scope, window or a contributing source.

    Shown, never merged: a footfall-freshness gap and the store-conversion gap
    that depends on it are two findings with two metric definitions, and
    collapsing them would leave the reader unable to tell which number is in
    question.

    Pairs are emitted in a stable order so a replay produces the same graph.
    """
    links: set[tuple[str, str]] = set()
    for i, left in enumerate(candidates):
        for right in candidates[i + 1 :]:
            if left.gap_type == right.gap_type and left.scope_id == right.scope_id:
                continue
            same_scope = (
                left.scope_type is right.scope_type
                and left.scope_id == right.scope_id
                and left.window == right.window
            )
            shared_source = bool(set(left.correlation_keys) & set(right.correlation_keys))
            if same_scope or shared_source:
                pair = tuple(
                    sorted(
                        [
                            f"{left.gap_type}:{left.scope_id}",
                            f"{right.gap_type}:{right.scope_id}",
                        ]
                    )
                )
                links.add((pair[0], pair[1]))
    return sorted(links)


def reconcile(
    runs: Sequence[DetectorRunResult],
    *,
    organization_id: UUID,
    open_gaps: Iterable[OpenGap] = (),
) -> PipelineResult:
    """Turn detector output into create/update decisions.

    An open gap with the same key is *updated*, not recreated: `first_seen_at`,
    `status` and `owner_id` are human state and a detector re-firing must not
    touch them. A terminal gap with the same key is ignored — the same condition
    recurring after somebody resolved it is a new finding, and pretending
    otherwise would resurrect closed work.
    """
    open_list = list(open_gaps)
    by_key = {gap.dedupe_key: gap for gap in open_list if not _is_terminal(gap.status)}

    all_candidates = [c for run in runs for c in run.candidates]
    # Positional rather than keyed by the candidate itself: `suppress` rebuilds
    # the ones it caps, so identity does not survive it and a `GapCandidate` is
    # not hashable by value either. The alignment is the contract `suppress`
    # documents and its test enforces.
    rules = [run.rule_id for run in runs for _ in run.candidates]

    kept, suppressed = suppress(all_candidates, open_gaps=open_list)
    if len(kept) != len(all_candidates):
        raise AssertionError(
            "suppress() changed the candidate count; the rule alignment below "
            "depends on it returning every candidate in order"
        )
    correlations = correlate(kept)

    outcomes: list[DedupeOutcome] = []
    # Within one reconciliation two candidates can collide on the same key —
    # two detector versions of the same rule, or a detector emitting the same
    # scope twice. The first wins and the second becomes an update, so the run
    # cannot violate the partial unique index it is about to write against.
    seen: dict[str, UUID | None] = {}
    for index, candidate in enumerate(kept):
        key = dedupe_key(
            candidate,
            organization_id=organization_id,
            rule_id=rules[index],
        )
        existing = by_key.get(key)
        if key in seen:
            decision = DedupeDecision.UPDATE
            existing_id = seen[key]
        elif existing is not None:
            decision = DedupeDecision.UPDATE
            existing_id = existing.gap_id
            seen[key] = existing_id
        else:
            decision = DedupeDecision.CREATE
            existing_id = None
            seen[key] = None
        outcomes.append(
            DedupeOutcome(
                dedupe_key=key,
                decision=decision,
                existing_gap_id=existing_id,
                candidate=candidate,
            )
        )

    return PipelineResult(
        outcomes=tuple(outcomes),
        suppressed=tuple(suppressed),
        correlations=tuple(correlations),
    )
