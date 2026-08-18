"""Gap endpoints: read, assign, transition, action, resolve.

Two things shape every handler here.

**No handler accepts an `organization_id`.** It comes from the principal and the
session is already bound to it, so a handler cannot address another tenant even
by mistake. The cross-tenant tests assert that rather than assuming it.

**Exposure is filtered server-side, not hidden in the UI.** A frontline token
receives a payload with no exposure fields at all — not zeroed, not masked,
absent. Masking in the client means the number crossed the wire, and anybody
who opens the network tab has it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from fitos_api.audit import record
from fitos_api.auth.deps import require, scoped_session
from fitos_api.auth.principal import Principal
from fitos_api.capabilities import Capability
from fitos_api.gaps.lifecycle import (
    DISMISSAL_REASONS,
    GapStatus,
    IllegalTransitionError,
    MissingRequirementError,
    NotPermittedError,
    TransitionRequest,
    VersionConflictError,
    legal_transitions,
    transition,
)
from fitos_api.models import Gap, GapAction, GapOutcome, Membership

router = APIRouter(prefix="/v1/gaps", tags=["gaps"])

# The fields a caller without `gap.view_exposure` never receives. Removed from
# the payload rather than nulled: a null field says "there is a number here you
# may not see", which is itself a disclosure on a ledger where most gaps carry
# one.
EXPOSURE_FIELDS = ("exposure_low", "exposure_base", "exposure_high", "currency", "assumptions")


class GapOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pack_key: str
    gap_type: str
    title: str
    summary: str
    scope_type: str
    scope_id: str
    metric_definition_id: uuid.UUID
    metric_version: int
    observed_value: float
    expected_value: float
    absolute_delta: float
    percentage_delta: float | None
    unit: str
    confidence_score: float | None
    confidence_band: str | None
    severity: str
    status: str
    owner_id: uuid.UUID | None
    first_seen_at: datetime
    last_seen_at: datetime
    as_of_at: datetime
    data_freshness_seconds: int | None
    rule_id: uuid.UUID
    rule_version: int
    detector_run_id: uuid.UUID
    evidence_refs: list[dict[str, Any]]
    reason_codes: list[str]
    lifecycle_version: int
    dismissal_reason_code: str | None
    dismissal_note: str | None
    resolved_at: datetime | None
    dismissed_at: datetime | None
    outcome_id: uuid.UUID | None

    # Present only for a caller holding gap.view_exposure.
    exposure_low: int | None = None
    exposure_base: int | None = None
    exposure_high: int | None = None
    currency: str | None = None
    assumptions: list[dict[str, Any]] | None = None


def serialise(gap: Gap, principal: Principal) -> dict[str, Any]:
    """One place the exposure filter is applied.

    A second serialisation path is how the rule gets broken: the list endpoint
    filters, somebody adds an export endpoint that does not, and the guarantee
    holds everywhere except the one route nobody tested.
    """
    payload = GapOut.model_validate(gap).model_dump()
    if not principal.can(Capability.GAP_VIEW_EXPOSURE):
        for field in EXPOSURE_FIELDS:
            payload.pop(field, None)
    return payload


class TransitionIn(BaseModel):
    to_status: GapStatus
    expected_version: int = Field(ge=1)
    reason_code: str | None = None
    note: str | None = None
    outcome_id: uuid.UUID | None = None


class AssignIn(BaseModel):
    # Membership id, not user id: ownership is org-scoped.
    owner_id: uuid.UUID | None
    expected_version: int = Field(ge=1)


class ActionIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    playbook_id: str | None = None
    assignee_id: uuid.UUID | None = None
    due_at: datetime | None = None


class ActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    gap_id: uuid.UUID
    title: str
    playbook_id: str | None
    assignee_id: uuid.UUID | None
    due_at: datetime | None
    status: str
    created_at: datetime
    completed_at: datetime | None


class OutcomeIn(BaseModel):
    action_id: uuid.UUID | None = None
    measurement_window_start: datetime
    measurement_window_end: datetime
    metric_definition_id: uuid.UUID
    metric_version: int = Field(ge=1)
    value_before: float
    value_after: float
    # `observed`, `pre_post` or `controlled_test`. Only the last may carry causal
    # language anywhere in the product, which is why it is a closed set rather
    # than free text.
    method: str
    notes: str | None = None


class OutcomeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    gap_id: uuid.UUID
    action_id: uuid.UUID | None
    measurement_window_start: datetime
    measurement_window_end: datetime
    metric_definition_id: uuid.UUID
    metric_version: int
    value_before: float
    value_after: float
    delta: float
    method: str
    notes: str | None
    recorded_at: datetime


def _load(session: Session, gap_id: uuid.UUID) -> Gap:
    found = session.get(Gap, gap_id)
    if found is None:
        # 404, not 403. A 403 would confirm the id exists in another
        # organization, which is the disclosure T2 is about.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="gap not found")
    return found


def _request_id(request: Request) -> str | None:
    return request.headers.get("x-request-id")


@router.get("")
def list_gaps(
    principal: Annotated[Principal, Depends(require(Capability.GAP_VIEW))],
    session: Annotated[Session, Depends(scoped_session)],
    gap_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    # No organization filter: RLS supplies it, and the cross-tenant test asserts
    # that is safe rather than assuming it.
    query = select(Gap).order_by(Gap.severity.desc(), Gap.last_seen_at.desc())
    if gap_status is not None:
        query = query.where(Gap.status == gap_status)
    query = query.limit(min(limit, 200)).offset(offset)
    return [serialise(gap, principal) for gap in session.execute(query).scalars().all()]


@router.get("/{gap_id}")
def get_gap(
    gap_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require(Capability.GAP_VIEW))],
    session: Annotated[Session, Depends(scoped_session)],
) -> dict[str, Any]:
    gap = _load(session, gap_id)
    payload = serialise(gap, principal)
    payload["legal_transitions"] = sorted(s.value for s in legal_transitions(GapStatus(gap.status)))
    return payload


@router.post("/{gap_id}/assign")
def assign_gap(
    gap_id: uuid.UUID,
    body: AssignIn,
    request: Request,
    principal: Annotated[Principal, Depends(require(Capability.GAP_ASSIGN))],
    session: Annotated[Session, Depends(scoped_session)],
) -> dict[str, Any]:
    gap = _load(session, gap_id)

    if gap.lifecycle_version != body.expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"gap is at version {gap.lifecycle_version}",
        )

    # RLS scopes this lookup, so a membership id from another organization simply
    # is not found. The check is here so assignment fails loudly rather than
    # storing an id that resolves to nobody.
    if body.owner_id is not None and session.get(Membership, body.owner_id) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="owner is not a member of this organization",
        )

    before = {"owner_id": str(gap.owner_id) if gap.owner_id else None}
    gap.owner_id = body.owner_id
    gap.lifecycle_version += 1
    session.flush()

    record(
        session,
        principal=principal,
        action="gap.assigned",
        object_type="gap",
        object_id=str(gap_id),
        before=before,
        after={"owner_id": str(gap.owner_id) if gap.owner_id else None},
        request_id=_request_id(request),
    )
    return serialise(gap, principal)


@router.post("/{gap_id}/transition")
def transition_gap(
    gap_id: uuid.UUID,
    body: TransitionIn,
    request: Request,
    # GAP_VIEW here, not GAP_TRANSITION: the specific capability depends on the
    # destination — dismissal needs its own — and `transition` checks it. A
    # blanket dependency would refuse a dismissal-only caller before the
    # lifecycle got a chance to allow it.
    principal: Annotated[Principal, Depends(require(Capability.GAP_VIEW))],
    session: Annotated[Session, Depends(scoped_session)],
) -> dict[str, Any]:
    gap = _load(session, gap_id)
    try:
        transition(
            session,
            gap,
            TransitionRequest(
                to_status=body.to_status,
                expected_version=body.expected_version,
                reason_code=body.reason_code,
                note=body.note,
                outcome_id=body.outcome_id,
            ),
            principal=principal,
            request_id=_request_id(request),
        )
    except NotPermittedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except VersionConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (IllegalTransitionError, MissingRequirementError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return serialise(gap, principal)


@router.get("/{gap_id}/actions", response_model=list[ActionOut])
def list_actions(
    gap_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require(Capability.GAP_VIEW))],
    session: Annotated[Session, Depends(scoped_session)],
) -> list[GapAction]:
    _load(session, gap_id)
    return list(
        session.execute(
            select(GapAction).where(GapAction.gap_id == gap_id).order_by(GapAction.created_at)
        )
        .scalars()
        .all()
    )


@router.post("/{gap_id}/actions", response_model=ActionOut, status_code=status.HTTP_201_CREATED)
def create_action(
    gap_id: uuid.UUID,
    body: ActionIn,
    request: Request,
    principal: Annotated[Principal, Depends(require(Capability.GAP_TRANSITION))],
    session: Annotated[Session, Depends(scoped_session)],
) -> GapAction:
    gap = _load(session, gap_id)
    if GapStatus(gap.status) in {GapStatus.RESOLVED, GapStatus.DISMISSED}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{gap.status} is terminal; actions belong to open work",
        )

    action = GapAction(
        organization_id=principal.organization_id,
        gap_id=gap_id,
        title=body.title,
        playbook_id=body.playbook_id,
        assignee_id=body.assignee_id,
        due_at=body.due_at,
        created_by=principal.membership_id,
    )
    session.add(action)
    session.flush()

    record(
        session,
        principal=principal,
        action="gap.action_created",
        object_type="gap_action",
        object_id=str(action.id),
        after={"gap_id": str(gap_id), "title": action.title},
        request_id=_request_id(request),
    )
    return action


@router.post("/{gap_id}/outcomes", response_model=OutcomeOut, status_code=status.HTTP_201_CREATED)
def record_outcome(
    gap_id: uuid.UUID,
    body: OutcomeIn,
    request: Request,
    principal: Annotated[Principal, Depends(require(Capability.GAP_TRANSITION))],
    session: Annotated[Session, Depends(scoped_session)],
) -> GapOutcome:
    """Record what happened. "No measurable change" is a complete outcome.

    `delta` is computed here rather than accepted from the caller: a delta that
    disagrees with its own before and after is the easiest possible way to
    misreport a result, and it would be invisible in the row.
    """
    _load(session, gap_id)

    outcome = GapOutcome(
        organization_id=principal.organization_id,
        gap_id=gap_id,
        action_id=body.action_id,
        measurement_window_start=body.measurement_window_start,
        measurement_window_end=body.measurement_window_end,
        metric_definition_id=body.metric_definition_id,
        metric_version=body.metric_version,
        value_before=body.value_before,
        value_after=body.value_after,
        delta=body.value_after - body.value_before,
        method=body.method,
        notes=body.notes,
        recorded_by=principal.membership_id,
        recorded_at=datetime.now(UTC),
    )
    session.add(outcome)
    session.flush()

    record(
        session,
        principal=principal,
        action="gap.outcome_recorded",
        object_type="gap_outcome",
        object_id=str(outcome.id),
        after={"gap_id": str(gap_id), "method": outcome.method, "delta": str(outcome.delta)},
        request_id=_request_id(request),
    )
    return outcome


@router.get("/meta/dismissal-reasons")
def dismissal_reasons(
    principal: Annotated[Principal, Depends(require(Capability.GAP_VIEW))],
) -> list[str]:
    """The closed set, served rather than duplicated in the client."""
    return list(DISMISSAL_REASONS)
