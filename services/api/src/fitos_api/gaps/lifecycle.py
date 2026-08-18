"""The gap lifecycle.

```text
Detected ──▶ Triaged ──▶ Investigating ──▶ Actioned ──▶ Validating ──▶ Resolved
    │           │              │              │             │
    └───────────┴──────────────┴──────────────┴─────────────┴──────▶ Dismissed
```

The transition table is data, not a chain of `if` statements, for one reason:
a chain of conditions is checked by reading it, and a table is checked by a
test that enumerates every pair. Twenty-one legal transitions out of forty-nine
possible ones means twenty-eight ways to be wrong, and nobody spots all of them
by reading.

Four rules apply to every transition, and each has a specific failure behind it:

**Permission.** `can("gap.transition")`, never `role == "manager"`. Dismissal is
a separate capability, because dismissing a gap is how a ledger gets quietly
emptied and it deserves its own grant.

**Optimistic concurrency.** Two people triaging the same gap from a stale list
must not silently overwrite each other. The second one gets a conflict and sees
what changed.

**Audit.** Actor, before, after and request id, written in the same transaction
as the change. An audit row that can be absent while the change succeeds is an
audit trail that proves nothing.

**Terminal states are terminal.** `Resolved` and `Dismissed` accept no
transitions at all. Reopening is not a transition — it is an explicit action
that creates new work, and modelling it as an edge here would let a detector
re-firing resurrect closed gaps.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from fitos_api.audit import record
from fitos_api.auth.principal import Principal
from fitos_api.capabilities import Capability
from fitos_api.models import Gap


class GapStatus(StrEnum):
    DETECTED = "detected"
    TRIAGED = "triaged"
    INVESTIGATING = "investigating"
    ACTIONED = "actioned"
    VALIDATING = "validating"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


TERMINAL: frozenset[GapStatus] = frozenset({GapStatus.RESOLVED, GapStatus.DISMISSED})

# Every legal transition, enumerated. Anything not here is refused.
#
# Forward-only along the chain, plus dismissal from anywhere non-terminal. There
# is deliberately no backward edge: a gap that went to `Actioned` prematurely is
# corrected by dismissing it and letting the detector raise it again, which
# leaves a record of the mistake. A silent step backwards leaves none.
TRANSITIONS: dict[GapStatus, frozenset[GapStatus]] = {
    GapStatus.DETECTED: frozenset({GapStatus.TRIAGED, GapStatus.DISMISSED}),
    GapStatus.TRIAGED: frozenset({GapStatus.INVESTIGATING, GapStatus.DISMISSED}),
    GapStatus.INVESTIGATING: frozenset({GapStatus.ACTIONED, GapStatus.DISMISSED}),
    GapStatus.ACTIONED: frozenset({GapStatus.VALIDATING, GapStatus.DISMISSED}),
    GapStatus.VALIDATING: frozenset({GapStatus.RESOLVED, GapStatus.DISMISSED}),
    GapStatus.RESOLVED: frozenset(),
    GapStatus.DISMISSED: frozenset(),
}

# Which capability each destination needs. Dismissal is separate from the rest
# because emptying a ledger is a different act from advancing work through it.
TRANSITION_CAPABILITY: dict[GapStatus, Capability] = {
    GapStatus.TRIAGED: Capability.GAP_TRANSITION,
    GapStatus.INVESTIGATING: Capability.GAP_TRANSITION,
    GapStatus.ACTIONED: Capability.GAP_TRANSITION,
    GapStatus.VALIDATING: Capability.GAP_TRANSITION,
    GapStatus.RESOLVED: Capability.GAP_TRANSITION,
    GapStatus.DISMISSED: Capability.GAP_DISMISS,
}

DISMISSAL_REASONS = (
    "not_a_problem",
    "known_and_accepted",
    "duplicate",
    "data_error",
    "out_of_scope",
    "already_fixed",
)


class TransitionError(Exception):
    """Base for every refusal, so a route can map them onto status codes."""


class IllegalTransitionError(TransitionError):
    """The destination is not reachable from the current status."""


class NotPermittedError(TransitionError):
    """The caller lacks the capability this transition needs."""


class VersionConflictError(TransitionError):
    """Somebody else changed the gap since the caller read it."""


class MissingRequirementError(TransitionError):
    """The transition is legal but its preconditions are not met."""


@dataclass(frozen=True)
class TransitionRequest:
    to_status: GapStatus
    expected_version: int
    reason_code: str | None = None
    note: str | None = None
    outcome_id: UUID | None = None


def legal_transitions(status: GapStatus) -> frozenset[GapStatus]:
    return TRANSITIONS[status]


def _snapshot(gap: Gap) -> dict[str, Any]:
    """Whole-field snapshot of what a transition touches.

    Not a diff: reconstructing a diff months later needs the schema as it was at
    the time, and a snapshot does not.
    """
    return {
        "status": gap.status,
        "owner_id": str(gap.owner_id) if gap.owner_id else None,
        "resolved_at": gap.resolved_at.isoformat() if gap.resolved_at else None,
        "dismissed_at": gap.dismissed_at.isoformat() if gap.dismissed_at else None,
        "outcome_id": str(gap.outcome_id) if gap.outcome_id else None,
        "version": gap.lifecycle_version,
    }


def transition(
    session: Session,
    gap: Gap,
    request: TransitionRequest,
    *,
    principal: Principal,
    request_id: str | None = None,
    now: datetime | None = None,
) -> Gap:
    """Move a gap to a new status, or refuse and say why.

    Checks run in this order deliberately: permission before legality, so a
    caller who may not act on gaps at all learns that rather than learning the
    shape of the workflow. Legality before concurrency, because an illegal
    destination is illegal at any version and re-reading would not help.
    """
    current = GapStatus(gap.status)
    target = request.to_status

    capability = TRANSITION_CAPABILITY[target]
    if not principal.can(capability):
        raise NotPermittedError(f"{principal.role.value} does not hold {capability.value}")

    if target not in TRANSITIONS[current]:
        if current in TERMINAL:
            raise IllegalTransitionError(
                f"{current.value} is terminal; reopening is a new gap, not a transition"
            )
        raise IllegalTransitionError(
            f"{current.value} -> {target.value} is not a legal transition; "
            f"from {current.value} you may reach "
            f"{sorted(s.value for s in TRANSITIONS[current])}"
        )

    if gap.lifecycle_version != request.expected_version:
        # Two people triaging from a stale list must not silently overwrite each
        # other. The loser is told what the current version is so the UI can
        # re-read and show what changed.
        raise VersionConflictError(
            f"gap is at version {gap.lifecycle_version}, "
            f"the caller expected {request.expected_version}"
        )

    _check_requirements(gap, request, target)

    before = _snapshot(gap)
    stamp = now or datetime.now(UTC)

    gap.status = target.value
    gap.lifecycle_version += 1
    gap.updated_at = stamp

    if target is GapStatus.RESOLVED:
        gap.resolved_at = stamp
        gap.outcome_id = request.outcome_id
    if target is GapStatus.DISMISSED:
        gap.dismissed_at = stamp
        gap.dismissal_reason_code = request.reason_code
        gap.dismissal_note = request.note

    session.flush()

    record(
        session,
        principal=principal,
        action=f"gap.{target.value}",
        object_type="gap",
        object_id=str(gap.id),
        before=before,
        after=_snapshot(gap),
        reason=request.reason_code,
        request_id=request_id,
    )
    return gap


def _check_requirements(gap: Gap, request: TransitionRequest, target: GapStatus) -> None:
    if target is GapStatus.DISMISSED:
        # A reason code and a note, both. The code makes dismissals countable —
        # "37% of gaps in this pack are dismissed as data_error" is a signal
        # about the pack, not about the people dismissing them — and the note is
        # what a colleague reads six weeks later.
        if request.reason_code not in DISMISSAL_REASONS:
            raise MissingRequirementError(
                f"dismissal needs a reason code from {list(DISMISSAL_REASONS)}, "
                f"got {request.reason_code!r}"
            )
        if not (request.note or "").strip():
            raise MissingRequirementError(
                "dismissal needs a note; a reason code alone does not tell the next "
                "person why this particular gap was not worth acting on"
            )

    if target is GapStatus.RESOLVED and request.outcome_id is None:
        # Invariant 4. "No measurable change" is a perfectly good outcome and is
        # as easy to record as a positive one — but resolving with no outcome at
        # all turns the ledger into a list of things somebody closed.
        raise MissingRequirementError(
            "resolution needs an outcome; recording no measurable change is an "
            "outcome, recording nothing is not"
        )

    if target is GapStatus.TRIAGED and gap.owner_id is None:
        raise MissingRequirementError(
            "triage sets an owner; a triaged gap nobody owns is an unread gap "
            "with a different label"
        )
