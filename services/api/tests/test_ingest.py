"""The ingestion boundary: uploads and signed webhooks.

The only place untrusted bytes enter the platform. Every test here is a
specific way that goes wrong, and most of them are things a browser will
cheerfully send.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jwt
import pytest
from conftest import requires_db
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from fitos_api.auth.tokens import TokenVerifier
from fitos_api.main import create_app
from fitos_api.models import Connection, Membership, User
from fitos_api.settings import Environment, Settings
from fitos_connector_sdk.raw_store import FilesystemRawStore
from fitos_connector_sdk.types import WebhookVerification
from fitos_connector_sdk.webhooks import compute_signature, header
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

pytestmark = requires_db

ISSUER = "https://fitos.local"
AUDIENCE = "fitos-api"
WEBHOOK_SECRET = "webhook-secret-value"


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


def auth(private: Any, user_id: uuid.UUID, org: uuid.UUID) -> dict[str, str]:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "org": str(org),
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + timedelta(minutes=10),
    }
    return {"Authorization": f"Bearer {jwt.encode(payload, private, algorithm='RS256')}"}


def _verify(connection: Any, raw: bytes, headers: dict[str, str]) -> WebhookVerification:
    """The app's webhook verifier, wired for tests.

    Deliberately the real signature check rather than a stub: a stubbed
    verifier would make every test below pass for the wrong reason.
    """
    from fitos_connector_sdk.webhooks import verify_signature

    signature = header(headers, "X-Signature")
    timestamp = header(headers, "X-Timestamp")
    if not signature or not timestamp:
        return WebhookVerification(ok=False, reason="missing headers")

    result = verify_signature(
        secret=WEBHOOK_SECRET, raw=raw, signature=signature, timestamp=timestamp
    )
    if not result.ok:
        return result
    delivery = header(headers, "X-Delivery-Id") or hashlib.sha256(raw).hexdigest()
    return WebhookVerification(ok=True, delivery_id=delivery)


@pytest.fixture
def client(app_engine: Engine, keypair: Any, tmp_path: Path) -> TestClient:
    _, public = keypair
    app = create_app(settings=Settings(environment=Environment.LOCAL))
    app.state.token_verifier = _StaticKeyVerifier(public)
    app.state.session_factory = sessionmaker(bind=app_engine, expire_on_commit=False)
    app.state.raw_store = FilesystemRawStore(tmp_path / "raw")
    app.state.webhook_verifier = _verify
    return TestClient(app)


@pytest.fixture
def world(owner_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]) -> dict[str, Any]:
    org_a, org_b = two_orgs
    out: dict[str, Any] = {"org_a": org_a, "org_b": org_b}
    for label, org in (("a", org_a), ("b", org_b)):
        user = User(email=f"ing-{label}-{uuid.uuid4().hex[:8]}@example.com")
        owner_session.add(user)
        owner_session.flush()
        owner_session.add(Membership(organization_id=org, user_id=user.id, role="admin"))
        connection = Connection(
            organization_id=org,
            connector_key="csv_upload",
            connector_version=1,
            name=f"upload-{label}",
            config={},
        )
        owner_session.add(connection)
        owner_session.flush()
        out[f"admin_{label}"] = user.id
        out[f"connection_{label}"] = connection.id
    owner_session.commit()
    return out


CSV = b"order_id,occurred_at,amount_minor,currency\nA-1,2026-05-01T10:00:00Z,1250,GBP\n"


def _upload(
    client: TestClient,
    private: Any,
    world: dict[str, Any],
    *,
    payload: bytes = CSV,
    content_type: str = "text/csv",
    filename: str = "orders.csv",
) -> Any:
    return client.post(
        "/v1/ingest/uploads",
        data={"connection_id": str(world["connection_a"]), "resource": "transactions"},
        files={"file": (filename, payload, content_type)},
        headers=auth(private, world["admin_a"], world["org_a"]),
    )


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------


def test_a_valid_csv_is_stored_before_it_is_parsed(
    client: TestClient, keypair: Any, world: dict[str, Any], tmp_path: Path
) -> None:
    """The raw object exists first, so a later failure still has bytes to show."""
    private, _ = keypair
    response = _upload(client, private, world)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["digest"] == hashlib.sha256(CSV).hexdigest()
    assert body["size_bytes"] == len(CSV)

    store = FilesystemRawStore(tmp_path / "raw")
    assert store.exists(body["raw_ref"])
    assert store.get(body["raw_ref"]) == CSV


def test_the_same_file_twice_produces_the_same_raw_reference(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    """A double upload is a no-op, not a duplicated day of revenue."""
    private, _ = keypair
    first = _upload(client, private, world)
    second = _upload(client, private, world)
    assert first.json()["raw_ref"] == second.json()["raw_ref"]


@pytest.mark.parametrize(
    ("payload", "description"),
    [
        (b"PK\x03\x04rest-of-a-zip", "zip"),
        (b"%PDF-1.7\n...", "PDF"),
        (b"\x7fELF\x02\x01\x01", "executable"),
        (b"<?xml version='1.0'?><x/>", "XML"),
        (b"<!DOCTYPE html><html></html>", "HTML"),
    ],
)
def test_a_file_declared_as_csv_that_is_not_is_refused(
    client: TestClient, keypair: Any, world: dict[str, Any], payload: bytes, description: str
) -> None:
    """Renaming a file changes nothing about what a parser will meet.

    Accepting it means the failure happens deeper in, with a worse message and
    after the bytes have already been treated as trustworthy.
    """
    private, _ = keypair
    response = _upload(client, private, world, payload=payload)
    assert response.status_code == 422, description
    assert "declared as CSV" in response.json()["detail"]


def test_an_unlisted_content_type_is_refused(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    private, _ = keypair
    response = _upload(
        client, private, world, content_type="application/x-msdownload", filename="x.exe"
    )
    assert response.status_code == 415


def test_an_empty_upload_is_refused(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    private, _ = keypair
    assert _upload(client, private, world, payload=b"").status_code == 422


def test_an_oversized_upload_is_refused(
    client: TestClient, keypair: Any, world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Capped while reading, not from Content-Length.

    That header is supplied by the client and absent on a chunked upload, so
    trusting it means the whole body arrives before anyone checks.
    """
    from fitos_api.routes import ingest

    monkeypatch.setattr(ingest, "MAX_UPLOAD_BYTES", 100)
    response = _upload(client, keypair[0], world, payload=b"x" * 500)
    assert response.status_code == 413


def test_a_malicious_filename_never_reaches_the_stored_path(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    """RELEASE GATE. A filename is whatever the client felt like sending.

    The key is derived from the organization, connector, resource and content
    digest. The filename is recorded for humans and used for nothing else.
    """
    private, _ = keypair
    response = _upload(
        client, private, world, filename="../../../../etc/passwd", content_type="text/csv"
    )
    assert response.status_code == 201
    key = response.json()["raw_ref"]
    assert ".." not in key
    assert "etc/passwd" not in key
    assert key.startswith(f"org/{world['org_a']}/csv_upload/transactions/")


def test_the_upload_is_stored_under_the_callers_organization_not_the_forms(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    """RELEASE GATE. organization_id comes from the token, never from the body."""
    private, _ = keypair
    response = client.post(
        "/v1/ingest/uploads",
        data={
            "connection_id": str(world["connection_a"]),
            "resource": "transactions",
            # Supplied deliberately; must be ignored entirely.
            "organization_id": str(world["org_b"]),
        },
        files={"file": ("orders.csv", CSV, "text/csv")},
        headers=auth(private, world["admin_a"], world["org_a"]),
    )
    assert response.status_code == 201
    assert response.json()["raw_ref"].startswith(f"org/{world['org_a']}/")


def test_uploading_to_another_organizations_connection_is_404(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    private, _ = keypair
    response = client.post(
        "/v1/ingest/uploads",
        data={"connection_id": str(world["connection_b"]), "resource": "transactions"},
        files={"file": ("orders.csv", CSV, "text/csv")},
        headers=auth(private, world["admin_a"], world["org_a"]),
    )
    assert response.status_code == 404


def test_an_upload_without_the_capability_is_403(
    client: TestClient, keypair: Any, world: dict[str, Any], owner_session: Session
) -> None:
    private, _ = keypair
    manager = owner_session.execute(
        text("SELECT user_id FROM memberships WHERE organization_id = :o AND role = 'manager'"),
        {"o": world["org_a"]},
    ).scalar_one()
    response = client.post(
        "/v1/ingest/uploads",
        data={"connection_id": str(world["connection_a"]), "resource": "transactions"},
        files={"file": ("orders.csv", CSV, "text/csv")},
        headers=auth(private, manager, world["org_a"]),
    )
    assert response.status_code == 403
    assert "source.manage" in response.json()["detail"]


def test_an_upload_is_audited_with_its_digest(
    client: TestClient, keypair: Any, world: dict[str, Any], owner_session: Session
) -> None:
    private, _ = keypair
    response = _upload(client, private, world)
    row = owner_session.execute(
        text("SELECT action, after FROM audit_events WHERE object_id = :o"),
        {"o": response.json()["raw_ref"]},
    ).one()
    assert row[0] == "upload.accepted"
    assert row[1]["digest"] == hashlib.sha256(CSV).hexdigest()


# ---------------------------------------------------------------------------
# Webhooks — release gate 8, over HTTP
# ---------------------------------------------------------------------------


def _signed_headers(
    body: bytes, *, delivery: str = "d-1", at: datetime | None = None
) -> dict[str, str]:
    timestamp = str(int((at or datetime.now(UTC)).timestamp()))
    return {
        "X-Signature": compute_signature(WEBHOOK_SECRET, timestamp, body),
        "X-Timestamp": timestamp,
        "X-Delivery-Id": delivery,
        "content-type": "application/json",
    }


BODY = json.dumps({"id": "w-1", "amount": 500}).encode()


def test_a_signed_delivery_is_accepted(client: TestClient, world: dict[str, Any]) -> None:
    response = client.post(
        f"/v1/ingest/webhooks/{world['org_a']}/{world['connection_a']}",
        content=BODY,
        headers=_signed_headers(BODY),
    )
    assert response.status_code == 200, response.text
    assert response.json()["duplicate"] is False


def test_the_same_delivery_twice_is_accepted_once(
    client: TestClient, world: dict[str, Any], owner_session: Session
) -> None:
    """RELEASE GATE. A retry is correct behaviour and must not create a second fact."""
    headers = _signed_headers(BODY, delivery="retry-me")

    first = client.post(
        f"/v1/ingest/webhooks/{world['org_a']}/{world['connection_a']}",
        content=BODY,
        headers=headers,
    )
    second = client.post(
        f"/v1/ingest/webhooks/{world['org_a']}/{world['connection_a']}",
        content=BODY,
        headers=headers,
    )

    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    # 200, not 409. An error makes the source retry harder.
    assert second.status_code == 200

    stored = owner_session.execute(
        text(
            "SELECT count(*) FROM webhook_deliveries "
            "WHERE organization_id = :o AND delivery_id = 'retry-me'"
        ),
        {"o": world["org_a"]},
    ).scalar_one()
    assert stored == 1


def test_two_tenants_can_use_the_same_delivery_id(
    client: TestClient, world: dict[str, Any]
) -> None:
    """Sources number deliveries from 1 for everybody; they will collide."""
    headers = _signed_headers(BODY, delivery="1")
    for org_key, connection_key in (("org_a", "connection_a"), ("org_b", "connection_b")):
        response = client.post(
            f"/v1/ingest/webhooks/{world[org_key]}/{world[connection_key]}",
            content=BODY,
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["duplicate"] is False, connection_key


def test_a_connection_paired_with_the_wrong_organization_is_refused(
    client: TestClient, world: dict[str, Any]
) -> None:
    """RELEASE GATE. The organization in the path opens the scope; RLS decides.

    Org A's id with org B's connection id finds nothing, because the lookup
    carries no organization predicate of its own — the policy supplies it. This
    is what stops the path parameter being authority rather than routing.
    """
    response = client.post(
        f"/v1/ingest/webhooks/{world['org_a']}/{world['connection_b']}",
        content=BODY,
        headers=_signed_headers(BODY, delivery="mismatched"),
    )
    assert response.status_code == 404


def test_a_tampered_body_is_refused(client: TestClient, world: dict[str, Any]) -> None:
    """The signature is over the exact bytes received."""
    headers = _signed_headers(BODY)
    response = client.post(
        f"/v1/ingest/webhooks/{world['org_a']}/{world['connection_a']}",
        content=BODY.replace(b"500", b"999999"),
        headers=headers,
    )
    assert response.status_code == 404


def test_an_unsigned_delivery_is_refused(client: TestClient, world: dict[str, Any]) -> None:
    """The endpoint is unauthenticated by design; the signature is the auth."""
    response = client.post(
        f"/v1/ingest/webhooks/{world['org_a']}/{world['connection_a']}",
        content=BODY,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 404


def test_a_stale_delivery_is_refused(client: TestClient, world: dict[str, Any]) -> None:
    """Without a timestamp inside the signature, a captured delivery lives forever."""
    old = datetime.now(UTC) - timedelta(hours=2)
    response = client.post(
        f"/v1/ingest/webhooks/{world['org_a']}/{world['connection_a']}",
        content=BODY,
        headers=_signed_headers(BODY, at=old),
    )
    assert response.status_code == 404


def test_an_unknown_connection_and_a_bad_signature_are_indistinguishable(
    client: TestClient, world: dict[str, Any]
) -> None:
    """Otherwise the endpoint is an oracle for enumerating connection ids."""
    unknown = client.post(
        f"/v1/ingest/webhooks/{world['org_a']}/{uuid.uuid4()}",
        content=BODY,
        headers=_signed_headers(BODY),
    )
    bad_signature = client.post(
        f"/v1/ingest/webhooks/{world['org_a']}/{world['connection_a']}",
        content=BODY,
        headers={**_signed_headers(BODY), "X-Signature": "0" * 64},
    )
    assert unknown.status_code == bad_signature.status_code == 404
    assert unknown.json()["detail"] == bad_signature.json()["detail"]


def test_the_delivery_is_stored_under_the_connections_organization(
    client: TestClient, world: dict[str, Any], owner_session: Session
) -> None:
    """RELEASE GATE. The tenant comes from the connection, never from the payload.

    A payload naming its own organization would be a cross-tenant write from an
    unauthenticated endpoint.
    """
    hostile = json.dumps({"id": "w-2", "organization_id": str(world["org_b"])}).encode()
    response = client.post(
        f"/v1/ingest/webhooks/{world['org_a']}/{world['connection_a']}",
        content=hostile,
        headers=_signed_headers(hostile, delivery="hostile-1"),
    )
    assert response.status_code == 200

    org = owner_session.execute(
        text("SELECT organization_id FROM webhook_deliveries WHERE delivery_id = 'hostile-1'")
    ).scalar_one()
    assert org == world["org_a"]


def test_the_raw_body_is_stored_for_every_accepted_delivery(
    client: TestClient, world: dict[str, Any], owner_session: Session, tmp_path: Path
) -> None:
    """A webhook that is accepted and not kept cannot be replayed or explained."""
    client.post(
        f"/v1/ingest/webhooks/{world['org_a']}/{world['connection_a']}",
        content=BODY,
        headers=_signed_headers(BODY, delivery="kept-1"),
    )
    raw_ref = owner_session.execute(
        text("SELECT raw_ref FROM webhook_deliveries WHERE delivery_id = 'kept-1'")
    ).scalar_one()

    assert raw_ref
    assert FilesystemRawStore(tmp_path / "raw").get(raw_ref) == BODY


def test_a_delivery_with_no_id_header_dedupes_on_its_content(
    client: TestClient, world: dict[str, Any]
) -> None:
    """A source with no delivery header must still not replay the same bytes."""
    headers = _signed_headers(BODY)
    headers.pop("X-Delivery-Id")

    first = client.post(
        f"/v1/ingest/webhooks/{world['org_a']}/{world['connection_a']}",
        content=BODY,
        headers=headers,
    )
    second = client.post(
        f"/v1/ingest/webhooks/{world['org_a']}/{world['connection_a']}",
        content=BODY,
        headers=headers,
    )

    assert first.json()["delivery_id"] == hashlib.sha256(BODY).hexdigest()
    assert second.json()["duplicate"] is True
