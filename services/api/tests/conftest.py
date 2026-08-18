"""Test database.

These tests need a real PostgreSQL: RLS cannot be exercised against SQLite or a
mock, and an untested RLS policy is worth nothing. If no database is reachable
the tenancy tests are skipped loudly rather than passing vacuously.

Point FITOS_TEST_DATABASE_URL at a superuser connection; the fixture creates a
throwaway database, applies the schema and the policies, and hands back an
engine connected as the unprivileged application role.

On the destructive-command rule in CLAUDE.md: this fixture creates and removes
a database whose name it generated itself, seconds earlier, containing only its
own fixtures. That is not the case the rule guards against — it exists to stop
destructive commands reaching tenant data outside the demo path. No tenant data
can exist in a database this fixture just created.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from fitos_api.auth.tokens import TokenVerifier
from fitos_api.main import create_app
from fitos_api.models import Base
from fitos_api.settings import Environment, Settings
from fitos_api.tenancy_sql import APP_ROLE, all_statements
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

ADMIN_URL = os.environ.get("FITOS_TEST_DATABASE_URL")
APP_PASSWORD = "test_only_not_a_secret"

# Skip locally, fail in CI.
#
# A developer without PostgreSQL should still be able to run the rest of the
# suite. But a CI run that silently skips every tenancy test is a green build
# with tenancy unverified — the same failure mode as a check stubbed green. CI
# sets FITOS_REQUIRE_DB_TESTS=1, which stops the skip; the app_engine fixture
# then raises, so the run fails loudly instead of passing quietly.
REQUIRE_DB = bool(os.environ.get("FITOS_REQUIRE_DB_TESTS"))

requires_db = pytest.mark.skipif(
    not ADMIN_URL and not REQUIRE_DB,
    reason="FITOS_TEST_DATABASE_URL not set; tenancy tests need real PostgreSQL",
)


def _swap_database(url: str, db_name: str) -> str:
    return url.rsplit("/", 1)[0] + f"/{db_name}"


@pytest.fixture(scope="session")
def db_name() -> str:
    return f"fitos_test_{uuid.uuid4().hex[:12]}"


@pytest.fixture(scope="session")
def app_engine(db_name: str) -> Iterator[Engine]:
    if not ADMIN_URL:
        if REQUIRE_DB:
            raise RuntimeError(
                "FITOS_REQUIRE_DB_TESTS is set but FITOS_TEST_DATABASE_URL is not. "
                "Tenancy tests must not be skipped in CI."
            )
        pytest.skip("no test database")

    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))

    owner_url = _swap_database(ADMIN_URL, db_name)
    owner = create_engine(owner_url, isolation_level="AUTOCOMMIT")
    Base.metadata.create_all(owner)
    with owner.connect() as conn:
        for statement in all_statements(APP_PASSWORD):
            conn.execute(text(statement))

    scheme, rest = owner_url.split("://", 1)
    host_part = rest.split("@", 1)[1]
    engine = create_engine(f"{scheme}://{APP_ROLE}:{APP_PASSWORD}@{host_part}")

    yield engine

    engine.dispose()
    owner.dispose()
    with admin.connect() as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :d AND pid <> pg_backend_pid()"
            ),
            {"d": db_name},
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
    admin.dispose()


@pytest.fixture
def owner_engine(app_engine: Engine, db_name: str) -> Iterator[Engine]:
    """Schema owner, exempt from RLS.

    Used only to arrange fixtures. Never to assert: asserting through a role
    that bypasses the policy proves nothing about the policy.
    """
    assert ADMIN_URL
    engine = create_engine(_swap_database(ADMIN_URL, db_name))
    yield engine
    engine.dispose()


@pytest.fixture
def owner_session(owner_engine: Engine) -> Iterator[Session]:
    with sessionmaker(bind=owner_engine)() as session:
        yield session


@pytest.fixture
def app_session(app_engine: Engine) -> Iterator[Session]:
    """Application-role session. NOBYPASSRLS — this is what production uses."""
    with sessionmaker(bind=app_engine)() as session:
        yield session
        session.rollback()


@pytest.fixture
def two_orgs(owner_session: Session) -> tuple[uuid.UUID, uuid.UUID]:
    """Two organizations, one membership each. The cross-tenant fixture."""
    from fitos_api.models import Membership, Organization, User

    org_a = Organization(slug=f"org-a-{uuid.uuid4().hex[:8]}", name="Org A")
    org_b = Organization(slug=f"org-b-{uuid.uuid4().hex[:8]}", name="Org B")
    user_a = User(email=f"a-{uuid.uuid4().hex[:8]}@example.test")
    user_b = User(email=f"b-{uuid.uuid4().hex[:8]}@example.test")
    owner_session.add_all([org_a, org_b, user_a, user_b])
    owner_session.flush()
    owner_session.add_all(
        [
            Membership(organization_id=org_a.id, user_id=user_a.id, role="manager"),
            Membership(organization_id=org_b.id, user_id=user_b.id, role="manager"),
        ]
    )
    owner_session.commit()
    return org_a.id, org_b.id


# ---------------------------------------------------------------------------
# The authenticated HTTP client
# ---------------------------------------------------------------------------
#
# Six suites had each grown their own copy of this. They are identical, and six
# copies of a JWT fixture is six places a signature check can be quietly
# loosened without anybody noticing the others still assert it. New suites take
# these; the existing local copies shadow them harmlessly and are worth
# collapsing onto these in a separate change.

ISSUER = "https://fitos.local"
AUDIENCE = "fitos-api"


@pytest.fixture(scope="module")
def keypair() -> tuple[Any, str]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        private.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private, public


class _StaticKeyVerifier(TokenVerifier):
    """Verifies against a fixed public key instead of fetching a JWKS.

    Only key *resolution* is stubbed. Signature, algorithm, issuer, audience and
    expiry checks all run exactly as in production — stubbing those would make
    these tests meaningless.
    """

    def __init__(self, public_key: str) -> None:
        super().__init__(jwks_url="http://unused.invalid", issuer=ISSUER, audience=AUDIENCE)
        object.__setattr__(self, "_public_key", public_key)

    def verify(self, token: str):  # type: ignore[no-untyped-def]
        return self.verify_with_key(token, self._public_key)  # type: ignore[attr-defined]


def token_for(private: Any, user_id: uuid.UUID, org_id: uuid.UUID) -> str:
    """A token proves identity and names an organization. Nothing else.

    There is deliberately no `role` parameter: the caller's authority comes from
    their membership row (ADR 0009). Tests that need a different role change the
    membership, which is what production does too.
    """
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "org": str(org_id),
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": now,
            "exp": now + timedelta(minutes=10),
        },
        private,
        algorithm="RS256",
    )


@pytest.fixture
def client(app_engine: Engine, keypair: Any) -> TestClient:
    _, public = keypair
    app = create_app(settings=Settings(environment=Environment.LOCAL))
    app.state.token_verifier = _StaticKeyVerifier(public)
    app.state.session_factory = sessionmaker(bind=app_engine, expire_on_commit=False)
    return TestClient(app)


def auth(private: Any, user_id: uuid.UUID, org: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(private, user_id, org)}"}
