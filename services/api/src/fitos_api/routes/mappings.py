"""Mapping version endpoints: create, preview, apply, compare, roll back.

The Phase C acceptance criterion is that a mapping version can be created,
previewed, backfilled, compared and rolled back **through the API** — so this is
the surface that criterion names, and each verb is a separate endpoint rather
than a `PATCH` with a mode flag, because they have genuinely different
authority and different consequences.

The shape that matters: a version is drafted, previewed against real records,
and only then applied. Applying deactivates the previous version in the same
transaction, so there is never a moment with two live mappings for one
resource — and never a moment with none, which would silently drop records
arriving mid-switch.

Rolling back is applying an earlier version, not deleting a later one. The
history stays intact, because a canonical row produced by version 3 has to
remain explicable after the rollback to version 2.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fitos_connector_sdk.mapping import (
    MappingSpec,
    UnknownTransformError,
    diff_mappings,
    preview,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fitos_api.audit import record
from fitos_api.auth.deps import require, scoped_session
from fitos_api.auth.principal import Principal
from fitos_api.capabilities import Capability
from fitos_api.models import Connection, MappingVersion

router = APIRouter(prefix="/v1/mappings", tags=["mappings"])


class MappingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_id: uuid.UUID
    resource: str = Field(min_length=1, max_length=64)
    target_table: str = Field(min_length=1, max_length=64)
    column_map: dict[str, str] = Field(min_length=1)
    required_columns: list[str] = Field(default_factory=list)
    transforms: dict[str, list[str]] = Field(default_factory=dict)
    note: str | None = None


class MappingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    connection_id: uuid.UUID
    resource: str
    version: int
    target_table: str
    column_map: dict[str, str]
    required_columns: list[str]
    transforms: dict[str, list[str]]
    is_active: bool
    applied_at: datetime | None
    note: str | None


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Sample records, supplied by the caller rather than re-fetched from the
    # source. Preview must not cause an extract: a preview with a side effect
    # is not a preview.
    records: list[dict[str, Any]] = Field(min_length=1, max_length=500)


class PreviewOut(BaseModel):
    sampled: int
    would_write: int
    would_quarantine: int
    rejection_rate: float
    rows: list[dict[str, Any]]
    rejections: list[dict[str, Any]]


class DiffOut(BaseModel):
    added_columns: list[str]
    removed_columns: list[str]
    changed_columns: list[dict[str, str]]
    added_required: list[str]
    removed_required: list[str]
    changed_transforms: list[str]
    is_empty: bool


def _spec(version: MappingVersion) -> MappingSpec:
    return MappingSpec(
        version=version.version,
        target_table=version.target_table,
        column_map=dict(version.column_map),
        required_columns=tuple(version.required_columns or []),
        transforms=dict(version.transforms or {}),
    )


def _load(session: Session, mapping_id: uuid.UUID) -> MappingVersion:
    found = session.get(MappingVersion, mapping_id)
    if found is None:
        # 404, not 403 — a 403 would confirm the id exists in another tenant.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="mapping version not found"
        )
    return found


@router.post("", response_model=MappingOut, status_code=status.HTTP_201_CREATED)
def create_mapping_version(
    body: MappingCreate,
    principal: Annotated[Principal, Depends(require(Capability.MAPPING_MANAGE))],
    session: Annotated[Session, Depends(scoped_session)],
) -> MappingVersion:
    """Draft a new version. Drafted, not applied — applying is a separate act."""
    connection = session.get(Connection, body.connection_id)
    if connection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="connection not found")

    try:
        # Validates the transform names before anything is written. A mapping
        # with a typo that quietly does nothing produces plausible wrong
        # numbers, which is worse than an error.
        MappingSpec(
            version=1,
            target_table=body.target_table,
            column_map=body.column_map,
            required_columns=tuple(body.required_columns),
            transforms=body.transforms,
        )
    except UnknownTransformError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    highest = session.execute(
        select(func.max(MappingVersion.version)).where(
            MappingVersion.connection_id == body.connection_id,
            MappingVersion.resource == body.resource,
        )
    ).scalar_one_or_none()

    version = MappingVersion(
        organization_id=principal.organization_id,
        connection_id=body.connection_id,
        resource=body.resource,
        version=(highest or 0) + 1,
        target_table=body.target_table,
        column_map=body.column_map,
        required_columns=body.required_columns,
        transforms=body.transforms,
        is_active=False,
        created_by_membership_id=principal.membership_id,
        note=body.note,
    )
    session.add(version)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="that version already exists"
        ) from exc

    record(
        session,
        principal=principal,
        action="mapping.created",
        object_type="mapping_version",
        object_id=str(version.id),
        after={"resource": version.resource, "version": version.version},
    )
    return version


@router.get("", response_model=list[MappingOut])
def list_mapping_versions(
    principal: Annotated[Principal, Depends(require(Capability.MAPPING_MANAGE))],
    session: Annotated[Session, Depends(scoped_session)],
    connection_id: uuid.UUID | None = None,
) -> list[MappingVersion]:
    # No organization filter: RLS supplies it.
    statement = select(MappingVersion).order_by(
        MappingVersion.resource, MappingVersion.version.desc()
    )
    if connection_id is not None:
        statement = statement.where(MappingVersion.connection_id == connection_id)
    return list(session.execute(statement).scalars().all())


@router.get("/{mapping_id}", response_model=MappingOut)
def get_mapping_version(
    mapping_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require(Capability.MAPPING_MANAGE))],
    session: Annotated[Session, Depends(scoped_session)],
) -> MappingVersion:
    return _load(session, mapping_id)


@router.post("/{mapping_id}/preview", response_model=PreviewOut)
def preview_mapping_version(
    mapping_id: uuid.UUID,
    body: PreviewRequest,
    principal: Annotated[Principal, Depends(require(Capability.MAPPING_MANAGE))],
    session: Annotated[Session, Depends(scoped_session)],
) -> PreviewOut:
    """What this version would do, using the real interpreter.

    Not an approximation of the mapping: `preview` calls the same
    `apply_mapping` a run does. A preview that approximates lies at exactly the
    moment somebody needs it — just before changing production data.
    """
    version = _load(session, mapping_id)
    result = preview(
        _spec(version),
        [(str(index), payload) for index, payload in enumerate(body.records)],
    )
    return PreviewOut(
        sampled=result.sampled,
        would_write=result.would_write,
        would_quarantine=result.would_quarantine,
        rejection_rate=result.rejection_rate,
        rows=[dict(row) for row in result.rows],
        rejections=[
            {
                "record": record_id,
                "reasons": [reason.model_dump(mode="json") for reason in reasons],
            }
            for record_id, reasons in result.rejections
        ],
    )


@router.post("/{mapping_id}/apply", response_model=MappingOut)
def apply_mapping_version(
    mapping_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require(Capability.MAPPING_MANAGE))],
    session: Annotated[Session, Depends(scoped_session)],
) -> MappingVersion:
    """Make this version live.

    Deactivating the previous version and activating this one happen in one
    transaction. Two live mappings would mean two answers to "how was this row
    produced"; zero would silently drop whatever arrived in the gap.
    """
    version = _load(session, mapping_id)
    if version.is_active:
        return version

    previous = session.execute(
        select(MappingVersion).where(
            MappingVersion.connection_id == version.connection_id,
            MappingVersion.resource == version.resource,
            MappingVersion.is_active.is_(True),
        )
    ).scalar_one_or_none()

    if previous is not None:
        previous.is_active = False
        previous.applied_at = None
        session.flush()

    version.is_active = True
    version.applied_at = datetime.now(UTC)
    session.flush()

    record(
        session,
        principal=principal,
        action="mapping.applied",
        object_type="mapping_version",
        object_id=str(version.id),
        before={"active_version": previous.version if previous else None},
        after={"active_version": version.version},
    )
    return version


@router.post("/{mapping_id}/rollback", response_model=MappingOut)
def rollback_to_mapping_version(
    mapping_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require(Capability.MAPPING_MANAGE))],
    session: Annotated[Session, Depends(scoped_session)],
) -> MappingVersion:
    """Go back to an earlier version.

    Rolling back re-applies an earlier version; it never deletes a later one.
    Rows produced by version 3 still have to be explicable after a rollback to
    version 2, and deleting 3 would make its own output unattributable.

    Audited separately from `apply` on purpose — "we rolled back" and "we
    applied a new mapping" are different events to whoever reads the log after
    an incident.
    """
    target = _load(session, mapping_id)

    current = session.execute(
        select(MappingVersion).where(
            MappingVersion.connection_id == target.connection_id,
            MappingVersion.resource == target.resource,
            MappingVersion.is_active.is_(True),
        )
    ).scalar_one_or_none()

    if current is not None and current.id == target.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="that version is already active"
        )
    if current is not None and target.version > current.version:
        # Rolling *forward* is applying, and it should be called that. The
        # distinction matters in the audit log.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="that version is newer than the active one; use apply",
        )

    if current is not None:
        current.is_active = False
        current.applied_at = None
        session.flush()

    target.is_active = True
    target.applied_at = datetime.now(UTC)
    session.flush()

    record(
        session,
        principal=principal,
        action="mapping.rolled_back",
        object_type="mapping_version",
        object_id=str(target.id),
        before={"active_version": current.version if current else None},
        after={"active_version": target.version},
    )
    return target


@router.get("/{mapping_id}/compare/{other_id}", response_model=DiffOut)
def compare_mapping_versions(
    mapping_id: uuid.UUID,
    other_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require(Capability.MAPPING_MANAGE))],
    session: Annotated[Session, Depends(scoped_session)],
) -> DiffOut:
    """Structured comparison, because the question is "what will this do".

    A textual diff of two JSON blobs answers a different question, and answers
    it worse.
    """
    before = _load(session, mapping_id)
    after = _load(session, other_id)

    if before.connection_id != after.connection_id or before.resource != after.resource:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="versions belong to different connections or resources",
        )

    diff = diff_mappings(_spec(before), _spec(after))
    return DiffOut(
        added_columns=list(diff.added_columns),
        removed_columns=list(diff.removed_columns),
        changed_columns=[
            {"column": column, "from": old, "to": new} for column, old, new in diff.changed_columns
        ],
        added_required=list(diff.added_required),
        removed_required=list(diff.removed_required),
        changed_transforms=list(diff.changed_transforms),
        is_empty=diff.is_empty,
    )
