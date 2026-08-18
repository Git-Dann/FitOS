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
- `organization_id` is read from the verified payload only. There is no code
  path that takes it from a header, body or query string.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import jwt
from jwt import PyJWKClient

from fitos_api.auth.principal import Principal
from fitos_api.capabilities import Capability, Role

# Asymmetric only. HS* would let anyone holding the public JWKS mint tokens.
ALLOWED_ALGORITHMS = ("RS256", "ES256", "EdDSA")

# Tolerance for clock skew between the issuer and this service.
LEEWAY_SECONDS = 30


class TokenError(Exception):
    """Verification failed. The message is safe to log; it never contains the token."""


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

    def verify(self, token: str) -> Principal:
        try:
            signing_key = self._jwk_client().get_signing_key_from_jwt(token)
        except Exception as exc:
            raise TokenError(f"could not resolve signing key: {type(exc).__name__}") from exc
        return self.verify_with_key(token, signing_key.key)

    def verify_with_key(self, token: str, key: Any) -> Principal:
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
        return principal_from_claims(payload)


def principal_from_claims(payload: dict[str, Any]) -> Principal:
    """Build a Principal from *verified* claims.

    Called only with a payload that has already passed signature, issuer,
    audience and expiry checks. Anything missing or malformed is a refusal, not
    a default — a token without an organization must not become a token with a
    convenient one.
    """
    try:
        user_id = UUID(str(payload["sub"]))
        organization_id = UUID(str(payload["org"]))
        membership_id = UUID(str(payload["mem"]))
        role = Role(str(payload["role"]))
    except KeyError as exc:
        raise TokenError(f"token missing required claim: {exc.args[0]}") from exc
    except ValueError as exc:
        raise TokenError(f"token claim malformed: {exc}") from exc

    raw_granted = payload.get("cap", [])
    if not isinstance(raw_granted, list):
        raise TokenError("token claim malformed: cap must be a list")
    try:
        granted = frozenset(Capability(str(c)) for c in raw_granted)
    except ValueError as exc:
        raise TokenError(f"token claim malformed: unknown capability ({exc})") from exc

    return Principal(
        user_id=user_id,
        organization_id=organization_id,
        membership_id=membership_id,
        role=role,
        granted=granted,
    )
