"""Token verification, including the attacks it exists to stop.

The algorithm-confusion tests are the ones that matter. A verifier that accepts
`alg: none`, or accepts HS256 signed with the public key, authenticates anyone
who can read the public JWKS — which is, by design, everyone.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fitos_api.auth.tokens import TokenError, TokenVerifier

ISSUER = "https://fitos.local"
AUDIENCE = "fitos-api"


@pytest.fixture(scope="module")
def keypair() -> tuple[Any, str]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = (
        private.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private, public_pem


@pytest.fixture
def verifier() -> TokenVerifier:
    return TokenVerifier(jwks_url="http://unused.invalid", issuer=ISSUER, audience=AUDIENCE)


def claims(**overrides: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    base: dict[str, Any] = {
        "sub": str(uuid.uuid4()),
        "org": str(uuid.uuid4()),
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + timedelta(minutes=10),
    }
    base.update(overrides)
    return base


def sign(private: Any, payload: dict[str, Any], algorithm: str = "RS256") -> str:
    return jwt.encode(payload, private, algorithm=algorithm)


def test_a_valid_token_yields_the_identity_it_proves(verifier: TokenVerifier, keypair: Any) -> None:
    private, public = keypair
    payload = claims()
    token = verifier.verify_with_key(sign(private, payload), public)

    assert str(token.user_id) == payload["sub"]
    assert str(token.organization_id) == payload["org"]


def test_role_and_capability_claims_are_not_read_at_all(
    verifier: TokenVerifier, keypair: Any
) -> None:
    """A token cannot describe its own authority (ADR 0009).

    `VerifiedToken` has no role and no capabilities to carry them into, so a
    forged or stale `role` claim has nowhere to land. What the caller may do is
    decided by the membership row, which the API reads under RLS on every
    request; test_api_tenancy proves the claim is ignored end to end.
    """
    private, public = keypair
    token = verifier.verify_with_key(
        sign(private, claims(role="owner", cap=["gap.view_exposure"], mem=str(uuid.uuid4()))),
        public,
    )

    assert not hasattr(token, "role")
    assert not hasattr(token, "capabilities")
    assert set(vars(token)) == {"user_id", "organization_id"}


def test_alg_none_is_rejected(verifier: TokenVerifier, keypair: Any) -> None:
    """The classic bypass: an unsigned token asserting whatever it likes."""
    _, public = keypair
    unsigned = jwt.encode(claims(role="owner"), key="", algorithm="none")
    with pytest.raises(TokenError):
        verifier.verify_with_key(unsigned, public)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def forge_hs256(payload: dict[str, Any], public_pem: str) -> str:
    """Hand-rolled HS256 token using the public key as the shared secret.

    Built by hand rather than with jwt.encode, because PyJWT refuses to treat a
    PEM as an HMAC secret. An attacker has no such scruples, so testing through
    PyJWT's encoder would prove nothing about our verifier.
    """
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64(json.dumps(payload, default=str).encode())
    signing_input = f"{header}.{body}".encode()
    signature = hmac.new(public_pem.encode(), signing_input, hashlib.sha256).digest()
    return f"{header}.{body}.{_b64(signature)}"


def test_hs256_signed_with_the_public_key_is_rejected(
    verifier: TokenVerifier, keypair: Any
) -> None:
    """Algorithm confusion — a total authentication bypass if it works.

    The public key is public. If the verifier accepts HS256, anyone who can
    fetch the JWKS can mint an owner token for any organization.
    """
    _, public = keypair
    payload = claims(role="owner")
    payload["iat"] = int(payload["iat"].timestamp())
    payload["exp"] = int(payload["exp"].timestamp())

    forged = forge_hs256(payload, public)

    # Sanity check with plain HMAC rather than PyJWT: PyJWT refuses a PEM as an
    # HMAC secret on decode as well as encode, so it cannot be used to confirm
    # the forgery. This proves the token really is a valid HS256 token under the
    # public key, so the test below fails for the right reason.
    header_b64, body_b64, sig_b64 = forged.split(".")
    expected = hmac.new(
        public.encode(), f"{header_b64}.{body_b64}".encode(), hashlib.sha256
    ).digest()
    assert _b64(expected) == sig_b64, "forgery is not a valid HS256 token"
    assert json.loads(base64.urlsafe_b64decode(body_b64 + "=="))["role"] == "owner"

    with pytest.raises(TokenError):
        verifier.verify_with_key(forged, public)


def test_an_expired_token_is_rejected(verifier: TokenVerifier, keypair: Any) -> None:
    private, public = keypair
    past = datetime.now(UTC) - timedelta(hours=2)
    token = sign(private, claims(iat=past, exp=past + timedelta(minutes=5)))
    with pytest.raises(TokenError):
        verifier.verify_with_key(token, public)


def test_a_token_for_another_audience_is_rejected(verifier: TokenVerifier, keypair: Any) -> None:
    private, public = keypair
    token = sign(private, claims(aud="some-other-service"))
    with pytest.raises(TokenError):
        verifier.verify_with_key(token, public)


def test_a_token_from_another_issuer_is_rejected(verifier: TokenVerifier, keypair: Any) -> None:
    private, public = keypair
    token = sign(private, claims(iss="https://attacker.example"))
    with pytest.raises(TokenError):
        verifier.verify_with_key(token, public)


def test_a_tampered_payload_is_rejected(verifier: TokenVerifier, keypair: Any) -> None:
    private, public = keypair
    header, _payload, signature = sign(private, claims()).split(".")
    other = sign(private, claims(role="owner")).split(".")[1]
    with pytest.raises(TokenError):
        verifier.verify_with_key(f"{header}.{other}.{signature}", public)


@pytest.mark.parametrize("missing", ["sub", "org"])
def test_a_missing_identity_claim_is_a_refusal_not_a_default(
    verifier: TokenVerifier, keypair: Any, missing: str
) -> None:
    private, public = keypair
    payload = claims()
    del payload[missing]
    with pytest.raises(TokenError):
        verifier.verify_with_key(sign(private, payload), public)


def test_the_error_never_contains_the_token(verifier: TokenVerifier, keypair: Any) -> None:
    """docs/threat-model.md T3 — a rejected token must not land in a log."""
    private, public = keypair
    token = sign(private, claims(aud="wrong"))
    with pytest.raises(TokenError) as exc:
        verifier.verify_with_key(token, public)
    assert token not in str(exc.value)
    assert token.split(".")[1] not in str(exc.value)


def test_a_malformed_organization_claim_is_refused(verifier: TokenVerifier, keypair: Any) -> None:
    private, public = keypair
    with pytest.raises(TokenError, match="malformed"):
        verifier.verify_with_key(sign(private, claims(org="not-a-uuid")), public)
