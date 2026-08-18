"""Membership endpoints.

The first org-scoped resource. It exists in Phase B mainly so the tenancy
guarantees have something real to be tested against — a cross-tenant negative
test needs an endpoint to be negative about.

Note what is absent: no handler accepts an `organization_id`. It comes from the
principal, and the session is already bound to it, so a handler cannot address
another tenant even by mistake.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from fitos_api.audit import record
from fitos_api.auth.deps import require, scoped_session
from fitos_api.auth.principal import Principal
from fitos_api.capabilities import Capability
from fitos_api.models import Membership

router = APIRouter(prefix="/v1/memberships", tags=["memberships"])


class MembershipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    role: str


class RoleChange(BaseModel):
    role: str


@router.get("", response_model=list[MembershipOut])
def list_memberships(
    principal: Annotated[Principal, Depends(require(Capability.MEMBER_MANAGE))],
    session: Annotated[Session, Depends(scoped_session)],
) -> list[Membership]:
    # No organization filter here on purpose: RLS supplies it. The
    # cross-tenant test asserts that this is safe rather than assuming it.
    return list(session.execute(select(Membership)).scalars().all())


@router.get("/{membership_id}", response_model=MembershipOut)
def get_membership(
    membership_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require(Capability.MEMBER_MANAGE))],
    session: Annotated[Session, Depends(scoped_session)],
) -> Membership:
    found = session.get(Membership, membership_id)
    if found is None:
        # 404, not 403. A 403 here would confirm the id exists in some other
        # organization, which is exactly the disclosure T2 is about.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="membership not found")
    return found


@router.patch("/{membership_id}", response_model=MembershipOut)
def change_role(
    membership_id: uuid.UUID,
    body: RoleChange,
    principal: Annotated[Principal, Depends(require(Capability.MEMBER_MANAGE))],
    session: Annotated[Session, Depends(scoped_session)],
) -> Membership:
    found = session.get(Membership, membership_id)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="membership not found")

    before = {"role": found.role}
    found.role = body.role
    session.flush()

    record(
        session,
        principal=principal,
        action="membership.role_changed",
        object_type="membership",
        object_id=str(membership_id),
        before=before,
        after={"role": found.role},
    )
    return found
