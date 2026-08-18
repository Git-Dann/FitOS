"""The invitation flow, end to end and against its edges.

Redemption is the one endpoint in the API that reaches an organization without a
membership already existing, so most of what is here is about the ways that
could go wrong: guessing codes, replaying one, arriving with a role you asked
for rather than the one you were offered, or two people redeeming at once.
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
from fitos_api.invitations import hash_secret, issue, parse
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


def token_for(private: Any, user_id: uuid.UUID, org_id: uuid.UUID | None = None) -> str:
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
    return jwt.encode(payload, private, algorithm="RS256")


def auth(private: Any, user_id: uuid.UUID, org_id: uuid.UUID | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(private, user_id, org_id)}"}


@pytest.fixture
def client(app_engine: Engine, keypair: Any) -> TestClient:
    _, public = keypair
    app = create_app(settings=Settings(environment=Environment.LOCAL))
    app.state.token_verifier = _StaticKeyVerifier(public)
    app.state.session_factory = sessionmaker(bind=app_engine, expire_on_commit=False)
    return TestClient(app)


@pytest.fixture
def world(owner_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]) -> dict[str, Any]:
    """An admin in each org, plus an outsider with an identity and no membership."""
    org_a, org_b = two_orgs
    admin_a = User(email=f"inv-admin-a-{uuid.uuid4().hex[:8]}@example.com")
    admin_b = User(email=f"inv-admin-b-{uuid.uuid4().hex[:8]}@example.com")
    outsider = User(email=f"outsider-{uuid.uuid4().hex[:8]}@example.com")
    owner_session.add_all([admin_a, admin_b, outsider])
    owner_session.flush()
    mem_a = Membership(organization_id=org_a, user_id=admin_a.id, role="admin")
    mem_b = Membership(organization_id=org_b, user_id=admin_b.id, role="admin")
    owner_session.add_all([mem_a, mem_b])
    owner_session.commit()
    return {
        "org_a": org_a,
        "org_b": org_b,
        "admin_a": admin_a.id,
        "admin_b": admin_b.id,
        "outsider": outsider.id,
        "outsider_email": outsider.email,
    }


def create(client: TestClient, private: Any, world: dict[str, Any], **body: Any) -> dict[str, Any]:
    payload = {"email": world["outsider_email"], "role": "manager"} | body
    r = client.post(
        "/v1/invitations", json=payload, headers=auth(private, world["admin_a"], world["org_a"])
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


# --------------------------------------------------------------------------
# The code is a credential
# --------------------------------------------------------------------------


def test_the_code_is_returned_once_and_never_stored(
    client: TestClient, keypair: Any, world: dict[str, Any], owner_session: Session
) -> None:
    """RELEASE GATE. A database read must not yield a usable invitation."""
    private, _ = keypair
    created = create(client, private, world)
    code = created["code"]

    stored = owner_session.execute(
        text("SELECT code_hash FROM invitations WHERE id = :i"), {"i": created["id"]}
    ).scalar_one()

    _, secret = code.split(".", 1)
    assert stored == hash_secret(secret)
    assert secret not in stored
    assert code not in stored

    # And there is no endpoint that hands it back.
    listed = client.get("/v1/invitations", headers=auth(private, world["admin_a"], world["org_a"]))
    assert listed.status_code == 200
    assert all("code" not in row for row in listed.json())


def test_the_audit_row_does_not_contain_the_code(
    client: TestClient, keypair: Any, world: dict[str, Any], owner_session: Session
) -> None:
    """Audit rows are readable by anyone with audit.view and are never deleted."""
    private, _ = keypair
    created = create(client, private, world)
    row = owner_session.execute(
        text("SELECT before, after FROM audit_events WHERE object_id = :o"),
        {"o": created["id"]},
    ).one()
    dumped = str(row)
    _, secret = created["code"].split(".", 1)
    assert secret not in dumped


def test_the_stored_hash_column_refuses_a_plaintext_code(
    owner_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """The constraint is what stops a later code path storing the secret itself."""
    from sqlalchemy.exc import IntegrityError

    org_a, _ = two_orgs
    with pytest.raises(IntegrityError, match="ck_invitation_code_hash_is_a_hash"):
        owner_session.execute(
            text(
                "INSERT INTO invitations "
                "(id, organization_id, email, role, code_hash, status, expires_at) "
                "VALUES (gen_random_uuid(), :o, 'x@example.com', 'manager', "
                "'a-plaintext-invitation-code', 'pending', now() + interval '1 day')"
            ),
            {"o": org_a},
        )
    owner_session.rollback()


# --------------------------------------------------------------------------
# Redemption
# --------------------------------------------------------------------------


def test_a_valid_code_creates_the_membership_it_offered(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    private, _ = keypair
    created = create(client, private, world, role="analyst")

    r = client.post(
        "/v1/invitations/accept",
        json={"code": created["code"]},
        headers=auth(private, world["outsider"]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["organization_id"] == str(world["org_a"])
    assert r.json()["role"] == "analyst"

    # And the new member can now act in that organization.
    session = client.get(
        "/v1/auth/session", headers=auth(private, world["outsider"], world["org_a"])
    )
    assert session.status_code == 200
    assert session.json()["role"] == "analyst"


def test_the_redeemer_cannot_choose_their_own_role(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    """RELEASE GATE. Role comes from the invitation row, never from the request."""
    private, _ = keypair
    created = create(client, private, world, role="frontline")

    r = client.post(
        "/v1/invitations/accept",
        json={"code": created["code"], "role": "owner", "granted_capabilities": ["org.manage"]},
        headers=auth(private, world["outsider"]),
    )
    assert r.status_code == 200
    assert r.json()["role"] == "frontline"

    caps = client.get(
        "/v1/auth/capabilities", headers=auth(private, world["outsider"], world["org_a"])
    )
    assert "org.manage" not in caps.json()


def test_a_code_can_only_be_redeemed_once(
    client: TestClient, keypair: Any, world: dict[str, Any], owner_session: Session
) -> None:
    private, _ = keypair
    created = create(client, private, world)

    first = client.post(
        "/v1/invitations/accept",
        json={"code": created["code"]},
        headers=auth(private, world["outsider"]),
    )
    assert first.status_code == 200

    other = User(email=f"second-{uuid.uuid4().hex[:8]}@example.com")
    owner_session.add(other)
    owner_session.commit()

    second = client.post(
        "/v1/invitations/accept",
        json={"code": created["code"]},
        headers=auth(private, other.id),
    )
    assert second.status_code == 404
    assert "not found or no longer valid" in second.json()["detail"]


def test_a_revoked_code_is_refused(client: TestClient, keypair: Any, world: dict[str, Any]) -> None:
    private, _ = keypair
    created = create(client, private, world)
    revoked = client.post(
        f"/v1/invitations/{created['id']}/revoke",
        headers=auth(private, world["admin_a"], world["org_a"]),
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"

    r = client.post(
        "/v1/invitations/accept",
        json={"code": created["code"]},
        headers=auth(private, world["outsider"]),
    )
    assert r.status_code == 404


def test_an_expired_code_is_refused(
    client: TestClient, keypair: Any, world: dict[str, Any], owner_session: Session
) -> None:
    private, _ = keypair
    created = create(client, private, world)
    # Both timestamps move, because `ck_invitation_expiry_future` refuses a row
    # whose expiry precedes its creation — an invitation cannot be born expired,
    # and this is what an eight-day-old one looks like.
    owner_session.execute(
        text(
            "UPDATE invitations SET created_at = now() - interval '8 days', "
            "expires_at = now() - interval '1 day' WHERE id = :i"
        ),
        {"i": created["id"]},
    )
    owner_session.commit()

    r = client.post(
        "/v1/invitations/accept",
        json={"code": created["code"]},
        headers=auth(private, world["outsider"]),
    )
    assert r.status_code == 404


def test_every_bad_code_gives_the_same_answer(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    """The endpoint must not be an oracle.

    Distinguishing "no such code" from "expired" from "wrong organization" tells
    a guesser which half of a code they got right, and tells anyone which
    addresses have been invited where.
    """
    private, _ = keypair
    created = create(client, private, world)
    _, secret = created["code"].split(".", 1)

    wrong_org = f"{world['org_b']}.{secret}"
    wrong_secret = f"{world['org_a']}.{issue(world['org_a']).code.split('.', 1)[1]}"
    nonsense = "not-a-code"
    unknown_org = f"{uuid.uuid4()}.{secret}"

    answers = set()
    for code in (wrong_org, wrong_secret, nonsense, unknown_org):
        r = client.post(
            "/v1/invitations/accept",
            json={"code": code},
            headers=auth(private, world["outsider"]),
        )
        answers.add((r.status_code, r.json()["detail"]))

    assert len(answers) == 1, f"redemption leaks which part was wrong: {answers}"
    assert answers.pop() == (404, "invitation not found or no longer valid")


def test_redeeming_needs_a_verified_identity(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    private, _ = keypair
    created = create(client, private, world)
    r = client.post("/v1/invitations/accept", json={"code": created["code"]})
    assert r.status_code == 401


def test_an_already_member_cannot_redeem_a_second_invitation(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    """The unique constraint is what stops a second membership, not a check."""
    private, _ = keypair
    created = create(client, private, world)
    assert (
        client.post(
            "/v1/invitations/accept",
            json={"code": created["code"]},
            headers=auth(private, world["outsider"]),
        ).status_code
        == 200
    )

    again = create(client, private, world)
    r = client.post(
        "/v1/invitations/accept",
        json={"code": again["code"]},
        headers=auth(private, world["outsider"]),
    )
    assert r.status_code == 409
    assert "already a member" in r.json()["detail"]


# --------------------------------------------------------------------------
# Cross-tenant
# --------------------------------------------------------------------------


def test_an_invitation_list_returns_only_the_callers_organization(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    private, _ = keypair
    mine = create(client, private, world)

    theirs = client.post(
        "/v1/invitations",
        json={"email": "elsewhere@example.com", "role": "manager"},
        headers=auth(private, world["admin_b"], world["org_b"]),
    )
    assert theirs.status_code == 201

    listed = client.get("/v1/invitations", headers=auth(private, world["admin_a"], world["org_a"]))
    ids = {row["id"] for row in listed.json()}
    assert ids == {mine["id"]}
    assert theirs.json()["id"] not in ids


def test_revoking_another_organizations_invitation_is_404(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    private, _ = keypair
    theirs = client.post(
        "/v1/invitations",
        json={"email": "elsewhere2@example.com", "role": "manager"},
        headers=auth(private, world["admin_b"], world["org_b"]),
    )
    assert theirs.status_code == 201

    r = client.post(
        f"/v1/invitations/{theirs.json()['id']}/revoke",
        headers=auth(private, world["admin_a"], world["org_a"]),
    )
    assert r.status_code == 404, "expected 404; 403 would confirm the invitation exists"


def test_a_manager_cannot_invite(
    client: TestClient, keypair: Any, world: dict[str, Any], owner_session: Session
) -> None:
    private, _ = keypair
    manager_user = owner_session.execute(
        text("SELECT user_id FROM memberships WHERE organization_id = :o AND role = 'manager'"),
        {"o": world["org_a"]},
    ).scalar_one()

    r = client.post(
        "/v1/invitations",
        json={"email": "nope@example.com", "role": "frontline"},
        headers=auth(private, manager_user, world["org_a"]),
    )
    assert r.status_code == 403
    assert "member.manage" in r.json()["detail"]


def test_a_second_pending_invitation_for_the_same_address_is_refused(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    private, _ = keypair
    create(client, private, world)
    r = client.post(
        "/v1/invitations",
        json={"email": world["outsider_email"], "role": "manager"},
        headers=auth(private, world["admin_a"], world["org_a"]),
    )
    assert r.status_code == 409


def test_presenter_demo_cannot_be_invited(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    """That role assumes a demo tenant; it is seeded, not offered."""
    private, _ = keypair
    r = client.post(
        "/v1/invitations",
        json={"email": "demo@example.com", "role": "presenter-demo"},
        headers=auth(private, world["admin_a"], world["org_a"]),
    )
    assert r.status_code == 422


# --------------------------------------------------------------------------
# Code handling
# --------------------------------------------------------------------------


def test_parse_never_returns_the_plaintext_secret() -> None:
    """So a caller cannot log or store it by accident after parsing."""
    org = uuid.uuid4()
    issued = issue(org)
    parsed_org, parsed_hash = parse(issued.code)
    assert parsed_org == org
    assert parsed_hash == issued.code_hash
    assert issued.code.split(".", 1)[1] not in parsed_hash


def test_two_codes_are_never_the_same() -> None:
    org = uuid.uuid4()
    codes = {issue(org).code for _ in range(100)}
    assert len(codes) == 100
