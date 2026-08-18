"""Token verification.

Better Auth issues; this verifies. The split is ADR 0005.

Every check here exists because its absence is a known attack:

- `algorithms` is an allowlist of asymmetric algorithms. Without it, a token
  claiming `alg: none` or `alg: HS256` signed with the *public* key verifies.
  This is the classic JWT confusion and it is a total authentication bypass.
- `audience` and `issuer` are required. A token minted for another service by
  the same identity provider must not authenticate here.
- Expiry is enforced with a small, explicit leeway rather than an open-ended
  one, so a long-expired token cannot be replayed because two clocks drifted.

What the token is *not* allowed to say is as important as what it proves. It
carries `sub` and `org` and nothing else that matters: identity, and which
organization the caller is asking to act in. Role and capabilities are resolved
from the database on every request (ADR 0009). A token that asserted its own
role would keep asserting it until expiry, so revoking an admin would take
effect whenever their token happened to run out. It also made the role claim
worth forging. Neither is acceptable for authorisation state.

Asking for an organization is not being granted it: `org` is a request, and the
membership lookup under RLS is what decides.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import jwt
from jwt import PyJWKClient

# Asymmetric only. HS* would let anyone holding the public JWKS mint tokens.
ALLOWED_ALGORITHMS = ("RS256", "ES256", "EdDSA")

# Tolerance for clock skew between the issuer and this service.
LEEWAY_SECONDS = 30


class TokenError(Exception):
    """Verification failed. The message is safe to log; it never contains the token."""


@dataclass(frozen=True)
class VerifiedToken:
    """What a valid token proves, and nothing more.

    `organization_id` is the organization the caller *asked* to act in. It is
    not authority to act there — `authenticated_context` still has to find a
    membership under RLS.
    """

    user_id: UUID
    organization_id: UUID


@dataclass(frozen=True)
class TokenVerifier:
    jwks_url: str
    issuer: str
    audience: str
    _client: PyJWKClient | None = None

    def _jwk_client(self) -> PyJWKClient:
        # cache_keys keeps a rotation from causing a fetch per request while
        # still picking up new keys by kid.
        return self._client or PyJWKClient(self.jwks_url, cache_keys=True)

    def verify(self, token: str) -> VerifiedToken:
        try:
            signing_key = self._jwk_client().get_signing_key_from_jwt(token)
        except Exception as exc:
            raise TokenError(f"could not resolve signing key: {type(exc).__name__}") from exc
        return self.verify_with_key(token, signing_key.key)

    def verify_with_key(self, token: str, key: Any) -> VerifiedToken:
        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=list(ALLOWED_ALGORITHMS),
                audience=self.audience,
                issuer=self.issuer,
                leeway=LEEWAY_SECONDS,
                options={
                    "require": ["exp", "iat", "iss", "aud", "sub"],
                    "verify_exp": True,
                    "verify_aud": True,
                    "verify_iss": True,
                    "verify_signature": True,
                },
            )
        except jwt.PyJWTError as exc:
            raise TokenError(f"token rejected: {type(exc).__name__}") from exc
        return token_from_claims(payload)


def token_from_claims(payload: dict[str, Any]) -> VerifiedToken:
    """Read the two claims that matter from an *already verified* payload.

    Anything missing or malformed is a refusal, not a default — a token without
    an organization must not become a token with a convenient one.
    """
    try:
        user_id = UUID(str(payload["sub"]))
        organization_id = UUID(str(payload["org"]))
    except KeyError as exc:
        raise TokenError(f"token missing required claim: {exc.args[0]}") from exc
    except ValueError as exc:
        raise TokenError(f"token claim malformed: {exc}") from exc

    return VerifiedToken(user_id=user_id, organization_id=organization_id)
