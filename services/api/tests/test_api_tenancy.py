"""Cross-tenant negative tests at the HTTP boundary.

The tests in test_tenancy.py prove the database refuses. These prove the API
refuses, and refuses in the right way: **404, not 403**, for an object that
exists in another organization. A 403 confirms the id is real, which is the
disclosure T2 exists to prevent.

Every org-scoped endpoint gets an entry here in the same commit that adds it —
that is the rule in CLAUDE.md, and `test_every_org_scoped_route_is_covered`
fails the build when someone forgets.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from conftest import requires_db
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from fitos_api.auth.tokens import TokenVerifier
from fitos_api.main import create_app
from fitos_api.models import Membership
from fitos_api.settings import Environment, Settings
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

pytestmark = requires_db

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


def token_for(
    private: Any, org_id: uuid.UUID, membership_id: uuid.UUID, role: str = "admin"
) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "org": str(org_id),
            "mem": str(membership_id),
            "role": role,
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


@pytest.fixture
def memberships(owner_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]) -> dict[str, Any]:
    org_a, org_b = two_orgs
    rows = owner_session.execute(
        text("SELECT id, organization_id FROM memberships WHERE organization_id = ANY(:o)"),
        {"o": [org_a, org_b]},
    ).all()
    by_org = {r[1]: r[0] for r in rows}
    return {"org_a": org_a, "org_b": org_b, "mem_a": by_org[org_a], "mem_b": by_org[org_b]}


def auth(private: Any, org: uuid.UUID, mem: uuid.UUID, role: str = "admin") -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(private, org, mem, role)}"}


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------


def test_no_token_is_401(client: TestClient) -> None:
    assert client.get("/v1/memberships").status_code == 401


def test_a_garbage_token_is_401(client: TestClient) -> None:
    r = client.get("/v1/memberships", headers={"Authorization": "Bearer not.a.token"})
    assert r.status_code == 401
    assert "not.a.token" not in r.text


# --------------------------------------------------------------------------
# Cross-tenant — the release gate
# --------------------------------------------------------------------------


def test_a_list_returns_only_the_callers_organization(
    client: TestClient, keypair: Any, memberships: dict[str, Any]
) -> None:
    private, _ = keypair
    r = client.get(
        "/v1/memberships", headers=auth(private, memberships["org_a"], memberships["mem_a"])
    )
    assert r.status_code == 200
    returned = {row["id"] for row in r.json()}
    assert returned == {str(memberships["mem_a"])}
    assert str(memberships["mem_b"]) not in returned


def test_reading_another_organizations_object_is_404_not_403(
    client: TestClient, keypair: Any, memberships: dict[str, Any]
) -> None:
    """RELEASE GATE.

    404 is deliberate. 403 would confirm the id exists somewhere, letting a
    caller enumerate another tenant's identifiers.
    """
    private, _ = keypair
    r = client.get(
        f"/v1/memberships/{memberships['mem_b']}",
        headers=auth(private, memberships["org_a"], memberships["mem_a"]),
    )
    assert r.status_code == 404, "expected 404; 403 would confirm the object exists"


def test_writing_to_another_organizations_object_is_404_not_403(
    client: TestClient, keypair: Any, memberships: dict[str, Any]
) -> None:
    private, _ = keypair
    r = client.patch(
        f"/v1/memberships/{memberships['mem_b']}",
        json={"role": "owner"},
        headers=auth(private, memberships["org_a"], memberships["mem_a"]),
    )
    assert r.status_code == 404


def test_a_write_refused_across_tenants_changes_nothing(
    client: TestClient, keypair: Any, memberships: dict[str, Any], owner_session: Session
) -> None:
    """A refusal must not be a partial success."""
    private, _ = keypair
    client.patch(
        f"/v1/memberships/{memberships['mem_b']}",
        json={"role": "owner"},
        headers=auth(private, memberships["org_a"], memberships["mem_a"]),
    )
    owner_session.expire_all()
    victim = owner_session.get(Membership, memberships["mem_b"])
    assert victim is not None
    assert victim.role == "manager", "a cross-tenant PATCH modified the target"


def test_a_nonexistent_id_is_also_404(
    client: TestClient, keypair: Any, memberships: dict[str, Any]
) -> None:
    """Same status as a foreign object, so the two are indistinguishable."""
    private, _ = keypair
    r = client.get(
        f"/v1/memberships/{uuid.uuid4()}",
        headers=auth(private, memberships["org_a"], memberships["mem_a"]),
    )
    assert r.status_code == 404


# --------------------------------------------------------------------------
# Capabilities
# --------------------------------------------------------------------------


def test_a_role_without_the_capability_is_403(
    client: TestClient, keypair: Any, memberships: dict[str, Any]
) -> None:
    """403 here is correct: the object is in the caller's own organization, so
    its existence is not a secret. Only the action is refused."""
    private, _ = keypair
    r = client.get(
        "/v1/memberships",
        headers=auth(private, memberships["org_a"], memberships["mem_a"], role="frontline"),
    )
    assert r.status_code == 403
    assert "member.manage" in r.json()["detail"]


# --------------------------------------------------------------------------
# Audit
# --------------------------------------------------------------------------


def test_a_successful_change_writes_an_audit_row(
    client: TestClient, keypair: Any, memberships: dict[str, Any], owner_session: Session
) -> None:
    private, _ = keypair
    r = client.patch(
        f"/v1/memberships/{memberships['mem_a']}",
        json={"role": "analyst"},
        headers=auth(private, memberships["org_a"], memberships["mem_a"]),
    )
    assert r.status_code == 200

    row = owner_session.execute(
        text(
            "SELECT action, before, after, organization_id FROM audit_events WHERE object_id = :oid"
        ),
        {"oid": str(memberships["mem_a"])},
    ).one()
    assert row[0] == "membership.role_changed"
    assert row[1] == {"role": "manager"}
    assert row[2] == {"role": "analyst"}
    assert row[3] == memberships["org_a"]


def test_a_refused_change_writes_no_audit_row(
    client: TestClient, keypair: Any, memberships: dict[str, Any], owner_session: Session
) -> None:
    private, _ = keypair
    client.patch(
        f"/v1/memberships/{memberships['mem_b']}",
        json={"role": "owner"},
        headers=auth(private, memberships["org_a"], memberships["mem_a"]),
    )
    count = owner_session.execute(
        text("SELECT count(*) FROM audit_events WHERE object_id = :oid"),
        {"oid": str(memberships["mem_b"])},
    ).scalar()
    assert count == 0


# --------------------------------------------------------------------------
# Coverage guard
# --------------------------------------------------------------------------


def test_every_org_scoped_route_is_covered_by_a_cross_tenant_test(client: TestClient) -> None:
    """Fails when an org-scoped route ships without a cross-tenant test.

    CLAUDE.md requires the negative test in the same commit as the endpoint.
    This is what makes that rule enforceable rather than aspirational: it lists
    the routes that depend on a tenant-scoped session and checks each appears in
    the covered set below.
    """
    covered = {"/v1/memberships", "/v1/memberships/{membership_id}"}

    org_scoped: set[str] = set()
    for route in client.app.routes:  # type: ignore[attr-defined]
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            continue
        names = {d.call.__name__ for d in dependant.dependencies if d.call is not None}
        if "scoped_session" in names:
            org_scoped.add(route.path)

    missing = org_scoped - covered
    assert not missing, f"org-scoped routes without a cross-tenant test: {sorted(missing)}"
