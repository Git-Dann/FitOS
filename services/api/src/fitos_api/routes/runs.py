"""Runs and backfills.

The API decides *that* a run should happen and records the intent; the worker
decides how. This separation is why the endpoints here are so thin: an API
process that extracted inline would hold a request open for the length of a
backfill, and a 30-second proxy timeout would silently orphan it halfway.

The backfill endpoint completes the Phase C acceptance list — a mapping version
can be created, previewed, **backfilled**, compared and rolled back through the
API. It plans the windows synchronously, because the plan is the part a person
needs to see before agreeing to it, and hands the plan to the workflow.

A backfill re-reads history through the *currently active* mapping. That is the
whole point: it is how a correction reaches rows that were already written,
without anything editing them in place.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from fitos_api.audit import record
from fitos_api.auth.deps import require, scoped_session
from fitos_api.auth.principal import Principal
from fitos_api.capabilities import Capability
from fitos_api.models import Connection, ConnectorRun, MappingVersion

router = APIRouter(prefix="/v1/runs", tags=["runs"])

# One window per day, matching the connector's own planner. Fixed rather than
# caller-supplied so the plan is deterministic and two people asking for the
# same range get the same answer.
BACKFILL_WINDOW = timedelta(days=1)

# A year of daily windows. Beyond this the caller almost certainly wants a
# different tool, and an accidental decade-long range should be refused rather
# than quietly queued.
MAX_WINDOWS = 366


class RunRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_id: uuid.UUID
    resources: list[str] = Field(min_length=1, max_length=20)


class BackfillRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_id: uuid.UUID
    resource: str
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def _range_is_sane(self) -> BackfillRequestBody:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if (self.end - self.start) > BACKFILL_WINDOW * MAX_WINDOWS:
            raise ValueError(f"a backfill may cover at most {MAX_WINDOWS} days")
        return self


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    connection_id: uuid.UUID
    connector_key: str
    mapping_version: int | None
    trigger: str
    outcome: str
    records_read: int
    records_written: int
    records_quarantined: int
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class BackfillAccepted(BaseModel):
    """The plan, returned before anything runs.

    A caller agreeing to a backfill should see how many windows it is. "This
    will re-read 366 days" is a different decision from "this will re-read
    two", and a progress bar afterwards is too late to make it.
    """

    connection_id: uuid.UUID
    resource: str
    mapping_version: int
    window_count: int
    windows: list[dict[str, str]]
    workflow_id: str


def _active_mapping(session: Session, connection_id: uuid.UUID, resource: str) -> MappingVersion:
    mapping = session.execute(
        select(MappingVersion).where(
            MappingVersion.connection_id == connection_id,
            MappingVersion.resource == resource,
            MappingVersion.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if mapping is None:
        # Refused rather than defaulted. Running with no mapping would write
        # nothing and report success, which is the worst combination.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"no active mapping version for {resource!r}; apply one first",
        )
    return mapping


def _connection(session: Session, connection_id: uuid.UUID) -> Connection:
    found = session.get(Connection, connection_id)
    if found is None:
        # 404, not 403 — a 403 would confirm the id exists in another tenant.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="connection not found")
    return found


def _schedule(request: Request) -> Any:
    """The workflow starter, injected at startup.

    Injected rather than imported so the API does not depend on the worker
    package, and so a test can assert what was scheduled without a Temporal
    server.
    """
    starter = getattr(request.app.state, "workflow_starter", None)
    if starter is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="the workflow engine is not configured",
        )
    return starter


@router.get("", response_model=list[RunOut])
def list_runs(
    principal: Annotated[Principal, Depends(require(Capability.SOURCE_VIEW))],
    session: Annotated[Session, Depends(scoped_session)],
    connection_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[ConnectorRun]:
    # No organization filter: RLS supplies it.
    statement = select(ConnectorRun).order_by(ConnectorRun.started_at.desc()).limit(min(limit, 200))
    if connection_id is not None:
        statement = statement.where(ConnectorRun.connection_id == connection_id)
    return list(session.execute(statement).scalars().all())


@router.get("/{run_id}", response_model=RunOut)
def get_run(
    run_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require(Capability.SOURCE_VIEW))],
    session: Annotated[Session, Depends(scoped_session)],
) -> ConnectorRun:
    found = session.get(ConnectorRun, run_id)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    return found


@router.post("", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED)
def start_run(
    body: RunRequestBody,
    request: Request,
    principal: Annotated[Principal, Depends(require(Capability.SOURCE_MANAGE))],
    session: Annotated[Session, Depends(scoped_session)],
) -> ConnectorRun:
    """Record the intent and hand it to the worker.

    202, not 200: the run has been accepted, not completed. Returning 200 with
    a `running` outcome invites a caller to treat the response as the result.
    """
    connection = _connection(session, body.connection_id)
    mapping = _active_mapping(session, body.connection_id, body.resources[0])

    run = ConnectorRun(
        organization_id=principal.organization_id,
        connection_id=connection.id,
        connector_key=connection.connector_key,
        connector_version=connection.connector_version,
        mapping_version=mapping.version,
        trigger="manual",
        outcome="running",
        resources=[{"resource": name, "outcome": "running"} for name in body.resources],
    )
    session.add(run)
    session.flush()

    _schedule(request)(
        "ConnectorRun",
        {
            "organization_id": str(principal.organization_id),
            "connection_id": str(connection.id),
            "connector_key": connection.connector_key,
            "connector_version": connection.connector_version,
            "resources": list(body.resources),
            "mapping_version": mapping.version,
            "trigger": "manual",
            "run_id": str(run.id),
        },
    )

    record(
        session,
        principal=principal,
        action="run.started",
        object_type="connector_run",
        object_id=str(run.id),
        after={"resources": list(body.resources), "mapping_version": mapping.version},
    )
    return run


@router.post("/backfill", response_model=BackfillAccepted, status_code=status.HTTP_202_ACCEPTED)
def start_backfill(
    body: BackfillRequestBody,
    request: Request,
    principal: Annotated[Principal, Depends(require(Capability.SOURCE_MANAGE))],
    session: Annotated[Session, Depends(scoped_session)],
) -> BackfillAccepted:
    """Re-read a date range through the currently active mapping.

    This is how a correction reaches rows that were already written: a new
    mapping version is applied, then history is re-read through it. Nothing
    edits a canonical row in place, so the old rows are replaced by the
    replacing engine on their natural key rather than mutated.

    The plan is computed here and returned, because "this will re-read 366
    days" is a decision the caller should make before it starts rather than
    discover from a progress bar.
    """
    connection = _connection(session, body.connection_id)
    mapping = _active_mapping(session, body.connection_id, body.resource)

    windows: list[dict[str, str]] = []
    cursor = body.start.astimezone(UTC)
    end = body.end.astimezone(UTC)
    while cursor < end:
        window_end = min(cursor + BACKFILL_WINDOW, end)
        windows.append({"start": cursor.isoformat(), "end": window_end.isoformat()})
        cursor = window_end

    workflow_id = f"backfill-{connection.id}-{body.resource}-{body.start.date()}"

    _schedule(request)(
        "Backfill",
        {
            "organization_id": str(principal.organization_id),
            "connection_id": str(connection.id),
            "connector_key": connection.connector_key,
            "connector_version": connection.connector_version,
            "resource": body.resource,
            "mapping_version": mapping.version,
            "windows": [(w["start"], w["end"]) for w in windows],
            "workflow_id": workflow_id,
        },
    )

    record(
        session,
        principal=principal,
        action="backfill.started",
        object_type="connection",
        object_id=str(connection.id),
        after={
            "resource": body.resource,
            "mapping_version": mapping.version,
            "window_count": len(windows),
            "start": body.start.isoformat(),
            "end": body.end.isoformat(),
        },
    )

    return BackfillAccepted(
        connection_id=connection.id,
        resource=body.resource,
        mapping_version=mapping.version,
        window_count=len(windows),
        windows=windows,
        workflow_id=workflow_id,
    )
