"""Session introspection and organization discovery.

Not a login implementation — Better Auth owns identity (ADR 0005). These three
endpoints exist because they answer *authorisation* questions, and only the API
can answer those consistently for the web app, the worker and the MCP server
alike.

`/capabilities` is what keeps capability checks out of the browser. The client
never maps a role to a permission set; it asks what this caller can do and hides
what is not there. The server still enforces every one of them — a hidden button
is a courtesy, not a control.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from fitos_api.auth.deps import current_principal, unscoped_session, verified_token
from fitos_api.auth.principal import Principal
from fitos_api.auth.tokens import VerifiedToken

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class SessionOut(BaseModel):
    user_id: uuid.UUID
    organization_id: uuid.UUID
    membership_id: uuid.UUID
    role: str
    capabilities: list[str]


class OrganizationOut(BaseModel):
    organization_id: uuid.UUID
    slug: str
    name: str
    role: str


@router.get("/session", response_model=SessionOut)
def read_session(principal: Annotated[Principal, Depends(current_principal)]) -> SessionOut:
    """Who the caller is in the organization they asked for.

    No capability is required: this returns only what the caller already proved
    and what the server already decided about them.
    """
    return SessionOut(
        user_id=principal.user_id,
        organization_id=principal.organization_id,
        membership_id=principal.membership_id,
        role=principal.role.value,
        capabilities=sorted(c.value for c in principal.capabilities),
    )


@router.get("/capabilities", response_model=list[str])
def read_capabilities(principal: Annotated[Principal, Depends(current_principal)]) -> list[str]:
    return sorted(c.value for c in principal.capabilities)


@router.get("/organizations", response_model=list[OrganizationOut])
def list_organizations(
    token: Annotated[VerifiedToken, Depends(verified_token)],
    session: Annotated[Session, Depends(unscoped_session)],
) -> list[OrganizationOut]:
    """The organizations this caller belongs to — the org switcher's data.

    Deliberately not org-scoped: the answer spans tenants, and it is the
    question whose answer lets a caller pick a tenant at all. It goes through
    `user_organizations`, a SECURITY DEFINER function that returns only the
    caller's own rows (see tenancy_sql.py for why that rather than a wider
    policy).

    The argument is the verified `sub` and nothing else. There is no request
    field that reaches it, so a caller cannot ask about somebody else.
    """
    rows = session.execute(
        text("SELECT organization_id, slug, name, role FROM user_organizations(:u)"),
        {"u": token.user_id},
    ).all()
    return [OrganizationOut(organization_id=r[0], slug=r[1], name=r[2], role=r[3]) for r in rows]
