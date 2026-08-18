"""Session introspection, capability discovery and the organization switcher.

`/v1/auth/organizations` is the only endpoint in the API that answers across
tenants, so most of this file is about the shape of that hole: it returns the
caller's own memberships and nothing else, and there is no request field that
reaches the argument deciding whose.
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
from fitos_api.capabilities import Capability, Role, capabilities_for
from fitos_api.main import create_app
from fitos_api.models import Membership, User
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
    def __init__(self, public_key: str) -> None:
        super().__init__(jwks_url="http://unused.invalid", issuer=ISSUER, audience=AUDIENCE)
        object.__setattr__(self, "_public_key", public_key)

    def verify(self, token: str):  # type: ignore[no-untyped-def]
        return self.verify_with_key(token, self._public_key)  # type: ignore[attr-defined]


def auth(private: Any, user_id: uuid.UUID, org_id: uuid.UUID | None = None) -> dict[str, str]:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + timedelta(minutes=10),
    }
    if org_id is not None:
        payload["org"] = str(org_id)
    return {"Authorization": f"Bearer {jwt.encode(payload, private, algorithm='RS256')}"}


@pytest.fixture
def client(app_engine: Engine, keypair: Any) -> TestClient:
    _, public = keypair
    app = create_app(settings=Settings(environment=Environment.LOCAL))
    app.state.token_verifier = _StaticKeyVerifier(public)
    app.state.session_factory = sessionmaker(bind=app_engine, expire_on_commit=False)
    return TestClient(app)


@pytest.fixture
def people(owner_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]) -> dict[str, Any]:
    """One user in both organizations, one user in only the second."""
    org_a, org_b = two_orgs
    both = User(email=f"both-{uuid.uuid4().hex[:8]}@example.com")
    only_b = User(email=f"onlyb-{uuid.uuid4().hex[:8]}@example.com")
    owner_session.add_all([both, only_b])
    owner_session.flush()
    owner_session.add_all(
        [
            Membership(organization_id=org_a, user_id=both.id, role="admin"),
            Membership(
                organization_id=org_b,
                user_id=both.id,
                role="frontline",
                granted_capabilities=["gap.view_exposure"],
            ),
            Membership(organization_id=org_b, user_id=only_b.id, role="manager"),
        ]
    )
    owner_session.commit()
    return {"org_a": org_a, "org_b": org_b, "both": both.id, "only_b": only_b.id}


# --------------------------------------------------------------------------
# Session and capabilities
# --------------------------------------------------------------------------


def test_the_session_describes_the_organization_that_was_asked_for(
    client: TestClient, keypair: Any, people: dict[str, Any]
) -> None:
    """The same user, the same identity, two different answers."""
    private, _ = keypair

    in_a = client.get("/v1/auth/session", headers=auth(private, people["both"], people["org_a"]))
    in_b = client.get("/v1/auth/session", headers=auth(private, people["both"], people["org_b"]))

    assert in_a.json()["role"] == "admin"
    assert in_b.json()["role"] == "frontline"
    assert in_a.json()["membership_id"] != in_b.json()["membership_id"]
    assert in_a.json()["user_id"] == in_b.json()["user_id"] == str(people["both"])


def test_capabilities_match_the_role_map_exactly(
    client: TestClient, keypair: Any, people: dict[str, Any]
) -> None:
    """The client must not have to know the map; nor may the server invent one."""
    private, _ = keypair
    r = client.get("/v1/auth/capabilities", headers=auth(private, people["both"], people["org_a"]))
    assert set(r.json()) == {c.value for c in capabilities_for(Role.ADMIN)}


def test_a_per_organization_grant_shows_up_in_capabilities(
    client: TestClient, keypair: Any, people: dict[str, Any]
) -> None:
    """The documented frontline exception, now sourced from the membership row.

    Frontline sees no modelled money by default; this membership was granted it.
    The same person in org A is an admin and sees it there anyway, which is what
    makes this a grant on a membership rather than on a user.
    """
    private, _ = keypair
    r = client.get("/v1/auth/capabilities", headers=auth(private, people["both"], people["org_b"]))
    caps = set(r.json())
    assert Capability.GAP_VIEW_EXPOSURE.value in caps
    assert Capability.GAP_ASSIGN.value not in caps, "the grant must not carry the whole role"


def test_a_capability_a_membership_does_not_grant_is_absent(
    client: TestClient, keypair: Any, people: dict[str, Any]
) -> None:
    private, _ = keypair
    r = client.get(
        "/v1/auth/capabilities", headers=auth(private, people["only_b"], people["org_b"])
    )
    assert Capability.MEMBER_MANAGE.value not in r.json()


def test_the_session_endpoint_still_requires_a_membership(
    client: TestClient, keypair: Any, people: dict[str, Any]
) -> None:
    """No capability is required, which is not the same as no authorisation."""
    private, _ = keypair
    r = client.get("/v1/auth/session", headers=auth(private, people["only_b"], people["org_a"]))
    assert r.status_code == 403


def test_an_identity_only_token_cannot_reach_an_org_scoped_route(
    client: TestClient, keypair: Any, people: dict[str, Any]
) -> None:
    """A token with no `org` is refused rather than defaulted to their only one.

    Defaulting would make the single-organization case work and the
    two-organization case a surprise, which is the worst way for this to fail.
    """
    private, _ = keypair
    r = client.get("/v1/auth/session", headers=auth(private, people["both"]))
    assert r.status_code == 403
    assert "names no organization" in r.json()["detail"]


# --------------------------------------------------------------------------
# The organization switcher — the one cross-tenant answer
# --------------------------------------------------------------------------


def test_the_switcher_lists_every_organization_the_caller_belongs_to(
    client: TestClient, keypair: Any, people: dict[str, Any]
) -> None:
    private, _ = keypair
    r = client.get("/v1/auth/organizations", headers=auth(private, people["both"]))
    assert r.status_code == 200
    by_org = {row["organization_id"]: row["role"] for row in r.json()}
    assert by_org[str(people["org_a"])] == "admin"
    assert by_org[str(people["org_b"])] == "frontline"


def test_the_switcher_lists_nothing_the_caller_does_not_belong_to(
    client: TestClient, keypair: Any, people: dict[str, Any]
) -> None:
    """RELEASE GATE. The cross-tenant function must not become a directory."""
    private, _ = keypair
    r = client.get("/v1/auth/organizations", headers=auth(private, people["only_b"]))
    returned = {row["organization_id"] for row in r.json()}
    assert returned == {str(people["org_b"])}
    assert str(people["org_a"]) not in returned


def test_the_switcher_answers_about_the_token_holder_only(
    client: TestClient, keypair: Any, people: dict[str, Any]
) -> None:
    """There is no request field that reaches the function's argument.

    Query, body and header are all tried. The answer is the token holder's list
    every time, because `sub` is the only thing that is ever passed.
    """
    private, _ = keypair
    headers = auth(private, people["only_b"])
    baseline = client.get("/v1/auth/organizations", headers=headers).json()

    attempts = [
        client.get(f"/v1/auth/organizations?user_id={people['both']}", headers=headers),
        client.get(f"/v1/auth/organizations?sub={people['both']}", headers=headers),
        client.get(
            "/v1/auth/organizations",
            headers=headers
            | {"X-User-Id": str(people["both"]), "X-Organization-Id": str(people["org_a"])},
        ),
        client.request(
            "GET", "/v1/auth/organizations", headers=headers, json={"user_id": str(people["both"])}
        ),
    ]
    for attempt in attempts:
        assert attempt.status_code == 200
        assert attempt.json() == baseline, "a request field influenced whose organizations"


def test_the_switcher_needs_a_verified_identity(client: TestClient) -> None:
    assert client.get("/v1/auth/organizations").status_code == 401


def test_the_function_is_not_executable_by_the_app_role_for_arbitrary_use(
    app_session: Session, people: dict[str, Any]
) -> None:
    """It returns only membership facts, and only for the id it is given.

    The application role can call it — it has to. What it cannot do is learn
    anything the caller could not already ask for, because the function exposes
    organization identity and role and nothing else.
    """
    columns = app_session.execute(
        text("SELECT * FROM user_organizations(:u)"), {"u": people["only_b"]}
    ).keys()
    assert set(columns) == {"organization_id", "slug", "name", "role"}


def test_the_function_leaks_nothing_when_asked_about_a_stranger(
    app_session: Session,
) -> None:
    rows = app_session.execute(
        text("SELECT * FROM user_organizations(:u)"), {"u": uuid.uuid4()}
    ).all()
    assert rows == []
