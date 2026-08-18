"""Request-scoped authentication and authorisation.

Four rules are enforced structurally rather than by review:

1. `organization_id` reaches a handler only through `Principal`, which is built
   only from a verified token claim plus a membership row. There is no
   dependency that reads it from a path, query, body or header.
2. A handler declares what it needs with `Depends(require(Capability.X))`. There
   is no way to reach a protected handler without naming a capability.
3. Role and capabilities come from the database, not from the token (ADR 0009).
   The token says who you are and which organization you are asking for; the
   `memberships` row says what you may do there. Revoking a membership or
   demoting a role therefore takes effect on the next request rather than at
   token expiry.
4. The membership lookup runs *inside* the tenant scope. Setting the scope to
   the requested organization and then finding no membership for the caller is
   the proof that they do not belong to it — RLS does the checking, so a
   forgotten `WHERE organization_id = ...` cannot open the door.

Missing or invalid credentials are 401. A capability the caller lacks is 403.
An object belonging to another organization is **404**, not 403: 403 confirms
the object exists, which is itself a disclosure (docs/threat-model.md T2).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from fitos_api.auth.principal import Principal
from fitos_api.auth.tokens import TokenError, TokenVerifier, VerifiedToken
from fitos_api.capabilities import Capability, Role
from fitos_api.db import organization_scope
from fitos_api.models import Membership

_bearer = HTTPBearer(auto_error=False)


@dataclass
class RequestContext:
    """The caller and the session they act through, resolved together.

    They are one dependency because they are one decision: the session is what
    establishes the tenant scope, and the tenant scope is what proves the
    principal. Splitting them would allow a handler to hold a principal for one
    organization and a session scoped to another.
    """

    principal: Principal
    session: Session


def get_verifier(request: Request) -> TokenVerifier:
    verifier: TokenVerifier | None = getattr(request.app.state, "token_verifier", None)
    if verifier is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="authentication is not configured",
        )
    return verifier


def verified_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    verifier: Annotated[TokenVerifier, Depends(get_verifier)],
) -> VerifiedToken:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return verifier.verify(credentials.credentials)
    except TokenError as exc:
        # The reason code is safe; the token is not, and never appears here.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def authenticated_context(
    request: Request,
    token: Annotated[VerifiedToken, Depends(verified_token)],
) -> Iterator[RequestContext]:
    """Open the tenant scope, then find out whether the caller belongs in it.

    The order matters. The scope is set from the *requested* organization, so
    the membership query below can only see rows in that organization; finding
    none means the caller is not a member of it. No membership, no principal,
    no handler.
    """
    if token.organization_id is None:
        # An identity-only token reaching an org-scoped route. There is nothing
        # to default to: picking "their only organization" would silently make
        # the single-org case work and the multi-org case a surprise.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="token names no organization",
        )
    factory = request.app.state.session_factory
    with factory() as session:
        with organization_scope(session, token.organization_id):
            membership = session.execute(
                select(Membership).where(Membership.user_id == token.user_id)
            ).scalar_one_or_none()
            if membership is None:
                # 403, not 404: the caller is authenticated, and the resource
                # in question is their own membership, so its absence discloses
                # nothing they did not already supply.
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="not a member of the requested organization",
                )
            yield RequestContext(
                # The organization is passed explicitly rather than re-read off
                # the token: it is non-optional from here on, and saying so
                # keeps the narrowing above from being undone by a later edit.
                principal=_principal_from(token.user_id, token.organization_id, membership),
                session=session,
            )
        session.commit()


def _principal_from(user_id: UUID, organization_id: UUID, membership: Membership) -> Principal:
    try:
        role = Role(membership.role)
    except ValueError as exc:
        # A role that is not in the enum is a schema or seeding fault, not a
        # caller fault, and must not be silently downgraded to "no capabilities".
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="membership has an unknown role",
        ) from exc

    raw = membership.granted_capabilities or []
    try:
        granted = frozenset(Capability(str(c)) for c in raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="membership grants an unknown capability",
        ) from exc

    return Principal(
        user_id=user_id,
        organization_id=organization_id,
        membership_id=membership.id,
        role=role,
        granted=granted,
    )


def current_principal(
    context: Annotated[RequestContext, Depends(authenticated_context)],
) -> Principal:
    return context.principal


def require(capability: Capability) -> Callable[[Principal], Principal]:
    """Declare the capability a handler needs.

    Returns the principal so a handler can depend on this instead of, rather
    than in addition to, `current_principal`.
    """

    def _check(
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Principal:
        if not principal.can(capability):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"missing capability: {capability.value}",
            )
        return principal

    return _check


def scoped_session(
    context: Annotated[RequestContext, Depends(authenticated_context)],
) -> Session:
    """The session the principal was resolved through, already tenant-scoped.

    A handler that opens its own session instead gets no tenant context and,
    because the policy denies when unset, sees nothing — which fails closed
    rather than open.
    """
    return context.session


def unscoped_session(request: Request) -> Iterator[Session]:
    """A session with no tenant context, for the two flows that precede one.

    Used only by invitation redemption and organization listing. Because the
    policies deny when `app.current_organization_id` is unset, a session from
    here sees nothing until the handler opens a scope deliberately — the failure
    mode of forgetting is an empty result, not a cross-tenant one.
    """
    factory = request.app.state.session_factory
    with factory() as session:
        yield session
        session.commit()
