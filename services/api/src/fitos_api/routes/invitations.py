"""Invitation endpoints.

Creating and revoking an invitation is org-scoped and needs `member.manage`.
Redeeming one is not: the whole point is that the redeemer is not yet a member,
so `POST /accept` takes an identity-only token and derives its organization from
the code rather than from the caller.

That makes redemption the one place in the API where an organization is reached
without a membership already existing, so it is worth being explicit about what
stops it being a hole:

- the code's organization half only *opens the scope*; the secret half, matched
  by hash inside that scope, is what authorises anything;
- role and capabilities come from the invitation row written by an admin, never
  from the request body — a redeemer cannot ask to arrive as an owner;
- the row is claimed with a conditional UPDATE, so two simultaneous redemptions
  produce one membership, not two.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fitos_api.audit import record
from fitos_api.auth.deps import require, scoped_session, unscoped_session, verified_token
from fitos_api.auth.principal import Principal
from fitos_api.auth.tokens import VerifiedToken
from fitos_api.capabilities import Capability, Role
from fitos_api.db import organization_scope
from fitos_api.invitations import InvalidCodeError, default_expiry, issue, parse
from fitos_api.models import Invitation, Membership, User

router = APIRouter(prefix="/v1/invitations", tags=["invitations"])


class InvitationCreate(BaseModel):
    email: EmailStr
    role: Role
    granted_capabilities: list[Capability] = []

    @field_validator("role")
    @classmethod
    def _not_a_demo_role(cls, value: Role) -> Role:
        # presenter-demo exists for the scripted demo story and is seeded, not
        # invited. Allowing it here would make a real tenant reachable by a role
        # whose whole design assumes a demo tenant.
        if value is Role.PRESENTER_DEMO:
            raise ValueError("presenter-demo is seeded on demo tenants, not invited")
        return value


class InvitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: str
    status: str
    expires_at: datetime


class InvitationCreated(InvitationOut):
    """The only response that ever contains the code.

    There is no endpoint that returns it again, because there is nothing to
    return it from — the database holds a digest.
    """

    code: str


class AcceptRequest(BaseModel):
    code: str


class AcceptResult(BaseModel):
    organization_id: uuid.UUID
    membership_id: uuid.UUID
    role: str


@router.post("", response_model=InvitationCreated, status_code=status.HTTP_201_CREATED)
def create_invitation(
    body: InvitationCreate,
    principal: Annotated[Principal, Depends(require(Capability.MEMBER_MANAGE))],
    session: Annotated[Session, Depends(scoped_session)],
) -> InvitationCreated:
    issued = issue(principal.organization_id)
    invitation = Invitation(
        organization_id=principal.organization_id,
        email=str(body.email).lower(),
        role=body.role.value,
        granted_capabilities=[c.value for c in body.granted_capabilities],
        code_hash=issued.code_hash,
        status="pending",
        invited_by_membership_id=principal.membership_id,
        expires_at=default_expiry(),
    )
    session.add(invitation)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="an invitation for that address is already pending",
        ) from exc

    record(
        session,
        principal=principal,
        action="invitation.created",
        object_type="invitation",
        object_id=str(invitation.id),
        # The code is deliberately absent. An audit row is a place secrets go to
        # live forever, and this one is readable by anyone with audit.view.
        after={"email": invitation.email, "role": invitation.role},
    )

    return InvitationCreated(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        status=invitation.status,
        expires_at=invitation.expires_at,
        code=issued.code,
    )


@router.get("", response_model=list[InvitationOut])
def list_invitations(
    principal: Annotated[Principal, Depends(require(Capability.MEMBER_MANAGE))],
    session: Annotated[Session, Depends(scoped_session)],
) -> list[Invitation]:
    # No organization filter: RLS supplies it.
    return list(session.execute(select(Invitation)).scalars().all())


@router.post("/{invitation_id}/revoke", response_model=InvitationOut)
def revoke_invitation(
    invitation_id: uuid.UUID,
    principal: Annotated[Principal, Depends(require(Capability.MEMBER_MANAGE))],
    session: Annotated[Session, Depends(scoped_session)],
) -> Invitation:
    invitation = session.get(Invitation, invitation_id)
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invitation not found")
    if invitation.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"invitation is {invitation.status}",
        )

    before = {"status": invitation.status}
    invitation.status = "revoked"
    invitation.revoked_at = datetime.now(UTC)
    session.flush()

    record(
        session,
        principal=principal,
        action="invitation.revoked",
        object_type="invitation",
        object_id=str(invitation.id),
        before=before,
        after={"status": invitation.status},
    )
    return invitation


@router.post("/accept", response_model=AcceptResult)
def accept_invitation(
    body: AcceptRequest,
    token: Annotated[VerifiedToken, Depends(verified_token)],
    session: Annotated[Session, Depends(unscoped_session)],
) -> AcceptResult:
    """Redeem a code. Identity is required; membership is what this creates.

    Every failure below is the same 404 with the same message. Distinguishing
    "no such code" from "expired" from "already used" would turn this endpoint
    into an oracle for guessing codes and for learning which addresses have been
    invited to which organization.
    """
    refusal = HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="invitation not found or no longer valid"
    )
    try:
        organization_id, code_hash = parse(body.code)
    except InvalidCodeError:
        raise refusal from None

    with organization_scope(session, organization_id):
        # Claim the row and check it is claimable in one statement. Two
        # redemptions racing each other both reach here; only one UPDATE matches
        # `status = 'pending'`, so only one proceeds to create a membership.
        now = datetime.now(UTC)
        claimed = session.execute(
            update(Invitation)
            .where(
                Invitation.code_hash == code_hash,
                Invitation.status == "pending",
                Invitation.expires_at > now,
            )
            .values(status="accepted", accepted_at=now, accepted_user_id=token.user_id)
            .returning(Invitation.id, Invitation.role, Invitation.granted_capabilities)
        ).one_or_none()
        if claimed is None:
            raise refusal

        invitation_id, role, granted = claimed

        # The user row is an identity mirror; Better Auth owns the credential.
        # A first-time invitee may have no mirror yet.
        user = session.get(User, token.user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="no user record for this identity",
            )

        membership = Membership(
            organization_id=organization_id,
            user_id=token.user_id,
            role=role,
            granted_capabilities=list(granted or []),
        )
        session.add(membership)
        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="already a member of that organization",
            ) from exc

        record(
            session,
            principal=Principal(
                user_id=token.user_id,
                organization_id=organization_id,
                membership_id=membership.id,
                role=Role(role),
            ),
            action="invitation.accepted",
            object_type="invitation",
            object_id=str(invitation_id),
            before={"status": "pending"},
            after={"status": "accepted", "membership_id": str(membership.id)},
        )

        return AcceptResult(
            organization_id=organization_id,
            membership_id=membership.id,
            role=role,
        )
