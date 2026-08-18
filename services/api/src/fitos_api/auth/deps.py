"""Request-scoped authentication and authorisation.

Two rules are enforced structurally rather than by review:

1. `organization_id` reaches a handler only through `Principal`, which is built
   only from verified token claims. There is no dependency that reads it from a
   path, query, body or header.
2. A handler declares what it needs with `Depends(require(Capability.X))`. There
   is no way to reach a protected handler without naming a capability.

Missing or invalid credentials are 401. A capability the caller lacks is 403.
An object belonging to another organization is **404**, not 403: 403 confirms
the object exists, which is itself a disclosure (docs/threat-model.md T2).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from fitos_api.auth.principal import Principal
from fitos_api.auth.tokens import TokenError, TokenVerifier
from fitos_api.capabilities import Capability
from fitos_api.db import organization_scope

_bearer = HTTPBearer(auto_error=False)


def get_verifier(request: Request) -> TokenVerifier:
    verifier: TokenVerifier | None = getattr(request.app.state, "token_verifier", None)
    if verifier is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="authentication is not configured",
        )
    return verifier


def current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    verifier: Annotated[TokenVerifier, Depends(get_verifier)],
) -> Principal:
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
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
) -> Iterator[Session]:
    """A session bound to the caller's organization for the whole request.

    Every org-scoped handler takes its session from here. A handler that opens
    its own session gets no tenant context and, because the policy denies when
    unset, sees nothing — which fails closed rather than open.
    """
    factory = request.app.state.session_factory
    with factory() as session:
        with organization_scope(session, principal.organization_id):
            yield session
        session.commit()
