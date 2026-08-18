"""The JWKS contract, across the runtime boundary.

ADR 0005 puts two processes in the authentication path: Better Auth in Node
issues, FastAPI in Python verifies. Testing each against its own fixtures proves
only that each agrees with itself. The interesting failures live in between —
an algorithm one side will not accept, a claim named differently, a key format
that decodes on one runtime and not the other — and none of them show up until
something real is signed on one side and read on the other.

So this mints a token from a real Better Auth instance backed by a real
migrated database, fetches the real JWKS, and puts both through the production
`TokenVerifier`. It is slow and it needs Node, a database and an install; that
is the price of the only test here that could catch an integration break.

Skipped without a database or without the web app's node_modules. In CI both
are present, and `FITOS_REQUIRE_JWKS_CONTRACT=1` turns the skip into an error so
the coverage cannot quietly disappear.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NoReturn

import pytest
from conftest import ADMIN_URL, requires_db
from fitos_api.auth.tokens import ALLOWED_ALGORITHMS, TokenError, TokenVerifier
from jwt import PyJWK
from sqlalchemy import create_engine, text

pytestmark = requires_db

REPO = Path(__file__).resolve().parents[3]
WEB = REPO / "apps" / "web"
API = REPO / "services" / "api"

ISSUER = "http://localhost:3000"
AUDIENCE = "fitos-api"
APP_PASSWORD = "contract_test_only"
AUTH_PASSWORD = "contract_test_only"

# Stable, because Better Auth encrypts the stored JWKS private key with it. A
# different secret on a later run cannot decrypt the key an earlier one wrote —
# worth knowing operationally: rotating BETTER_AUTH_SECRET invalidates every
# stored signing key, it does not re-encrypt them.
SECRET = "contract-test-secret-not-a-production-value-0000000"

REQUIRE = bool(os.environ.get("FITOS_REQUIRE_JWKS_CONTRACT"))


def _skip_or_fail(reason: str) -> NoReturn:
    """NoReturn is accurate — both branches raise — and it is what lets the
    caller's `is None` checks narrow for the type checker."""
    if REQUIRE:
        pytest.fail(f"FITOS_REQUIRE_JWKS_CONTRACT is set but {reason}")
    pytest.skip(reason)


def _decode_segment(token: str, index: int) -> dict[str, Any]:
    segment = token.split(".")[index]
    decoded = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    return dict(json.loads(decoded))


@pytest.fixture(scope="module")
def issued() -> Iterator[dict[str, Any]]:
    """A token and JWKS from a real Better Auth against a real migrated schema."""
    if not (WEB / "node_modules" / "better-auth").exists():
        _skip_or_fail("apps/web dependencies are not installed")
    pnpm = shutil.which("pnpm")
    uv = shutil.which("uv")
    if pnpm is None or uv is None:
        _skip_or_fail("pnpm or uv is not on PATH")
    assert ADMIN_URL

    name = f"fitos_jwks_{uuid.uuid4().hex[:12]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))

    sqlalchemy_url = ADMIN_URL.rsplit("/", 1)[0] + f"/{name}"
    migrate = subprocess.run(
        [uv, "run", "python", "-m", "alembic", "upgrade", "head"],
        cwd=API,
        env={
            **os.environ,
            "FITOS_MIGRATION_DATABASE_URL": sqlalchemy_url,
            "FITOS_APP_ROLE_PASSWORD": APP_PASSWORD,
            "FITOS_AUTH_ROLE_PASSWORD": AUTH_PASSWORD,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert migrate.returncode == 0, f"alembic upgrade failed:\n{migrate.stderr}"

    # Better Auth connects through node-postgres, not SQLAlchemy, and as the
    # identity role rather than the owner — so this also checks that migration
    # 0004 granted that role enough to work.
    host_and_db = sqlalchemy_url.split("://", 1)[1].split("@", 1)[1]
    node_url = f"postgresql://fitos_auth:{AUTH_PASSWORD}@{host_and_db}"

    result = subprocess.run(
        [pnpm, "--silent", "run", "issue-token"],
        cwd=WEB,
        env={
            **os.environ,
            "BETTER_AUTH_SECRET": SECRET,
            "FITOS_AUTH_DATABASE_URL": node_url,
            "FITOS_AUTH_ISSUER": ISSUER,
            "FITOS_AUTH_AUDIENCE": AUDIENCE,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"issuing a token failed:\n{result.stderr}"

    payload = json.loads(result.stdout.strip().splitlines()[-1])
    yield payload

    with admin.connect() as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :d AND pid <> pg_backend_pid()"
            ),
            {"d": name},
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    admin.dispose()


@pytest.fixture(scope="module")
def signing_key(issued: dict[str, Any]) -> Any:
    keys = issued["jwks"]["keys"]
    assert len(keys) >= 1, "Better Auth published no keys"
    return PyJWK.from_dict(keys[0]).key


@pytest.fixture
def verifier() -> TokenVerifier:
    return TokenVerifier(jwks_url="http://unused.invalid", issuer=ISSUER, audience=AUDIENCE)


def test_the_api_accepts_a_token_better_auth_actually_issued(
    verifier: TokenVerifier, issued: dict[str, Any], signing_key: Any
) -> None:
    """RELEASE GATE. The two halves of the auth path agree in practice."""
    token = verifier.verify_with_key(issued["token"], signing_key)
    assert str(token.user_id) == issued["userId"]


def test_the_published_key_is_asymmetric_and_public(issued: dict[str, Any]) -> None:
    """A symmetric key in a public JWKS is a key anyone can sign with."""
    for key in issued["jwks"]["keys"]:
        assert key["kty"] in {"OKP", "EC", "RSA"}, key["kty"]
        assert "d" not in key, "the private component was published in the JWKS"
        assert "k" not in key, "a symmetric key was published in the JWKS"


def test_the_issuing_algorithm_is_one_the_api_allows(issued: dict[str, Any]) -> None:
    """Catches a default moving on either side.

    Better Auth's key type and the API's allowlist are configured
    independently. If either changes, every token silently fails to verify in
    production; here it fails in CI instead.
    """
    header = _decode_segment(issued["token"], 0)
    assert header["alg"] in ALLOWED_ALGORITHMS, (
        f"Better Auth issued {header['alg']}, which the API refuses"
    )
    assert header.get("kid"), "no kid, so key rotation cannot work"


def test_a_real_token_is_still_refused_for_the_wrong_audience(
    issued: dict[str, Any], signing_key: Any
) -> None:
    """A valid signature is not enough. A token for another service must not work."""
    other = TokenVerifier(jwks_url="u", issuer=ISSUER, audience="some-other-service")
    with pytest.raises(TokenError):
        other.verify_with_key(issued["token"], signing_key)


def test_a_real_token_is_still_refused_from_the_wrong_issuer(
    issued: dict[str, Any], signing_key: Any
) -> None:
    other = TokenVerifier(jwks_url="u", issuer="https://attacker.example", audience=AUDIENCE)
    with pytest.raises(TokenError):
        other.verify_with_key(issued["token"], signing_key)


def test_the_identity_id_is_a_uuid_the_membership_table_can_reference(
    issued: dict[str, Any],
) -> None:
    """Better Auth generates string ids by default; memberships.user_id is uuid.

    `advanced.database.generateId` is configured to emit UUIDs for exactly this
    reason, and this is what notices if that configuration is dropped.
    """
    assert uuid.UUID(issued["userId"])


def test_a_token_with_no_active_organization_carries_no_org_claim(
    issued: dict[str, Any],
) -> None:
    """A fresh user belongs to nothing, and the token must not pretend otherwise.

    `definePayload` reads the active organization; with none set the claim is
    absent rather than empty or defaulted, and the API routes such a token to
    the identity-only endpoints (ADR 0009).
    """
    body = _decode_segment(issued["token"], 1)
    assert body.get("org") is None
    assert body["iss"] == ISSUER
    assert body["aud"] == AUDIENCE
    assert {"sub", "iat", "exp"} <= set(body)
