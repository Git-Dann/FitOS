"""Runs and backfills through the API.

The backfill endpoint completes the Phase C acceptance list: a mapping version
can be created, previewed, **backfilled**, compared and rolled back through the
API. The other tests here are about the two ways a run endpoint goes quietly
wrong — running with no mapping, and reporting acceptance as completion.
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
from fitos_api.models import Connection, MappingVersion, Membership, User
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


@pytest.fixture
def scheduled() -> list[tuple[str, dict[str, Any]]]:
    """What the API asked the workflow engine to do.

    Injected rather than a real Temporal client: this suite is about what the
    API decides, and the workflows have their own tests against a real server.
    """
    return []


@pytest.fixture
def client(app_engine: Engine, keypair: Any, scheduled: list[Any]) -> TestClient:
    _, public = keypair
    app = create_app(settings=Settings(environment=Environment.LOCAL))
    app.state.token_verifier = _StaticKeyVerifier(public)
    app.state.session_factory = sessionmaker(bind=app_engine, expire_on_commit=False)
    app.state.workflow_starter = lambda name, payload: scheduled.append((name, payload))
    return TestClient(app)


@pytest.fixture
def world(owner_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]) -> dict[str, Any]:
    """An admin, a connection and an active mapping in each organization."""
    org_a, org_b = two_orgs
    out: dict[str, Any] = {"org_a": org_a, "org_b": org_b}
    for label, org in (("a", org_a), ("b", org_b)):
        user = User(email=f"run-{label}-{uuid.uuid4().hex[:8]}@example.com")
        owner_session.add(user)
        owner_session.flush()
        owner_session.add(Membership(organization_id=org, user_id=user.id, role="admin"))
        connection = Connection(
            organization_id=org,
            connector_key="generic_rest",
            connector_version=1,
            name=f"src-{label}",
            config={"base_url": "https://api.example"},
        )
        owner_session.add(connection)
        owner_session.flush()
        owner_session.add(
            MappingVersion(
                organization_id=org,
                connection_id=connection.id,
                resource="records",
                version=4,
                target_table="stg_records",
                column_map={"order_id": "id"},
                is_active=True,
                applied_at=datetime.now(UTC),
            )
        )
        out[f"admin_{label}"] = user.id
        out[f"connection_{label}"] = connection.id
    owner_session.commit()
    return out


# ---------------------------------------------------------------------------
# Backfill — the acceptance criterion
# ---------------------------------------------------------------------------


def test_a_backfill_can_be_started_through_the_api(
    client: TestClient, keypair: Any, world: dict[str, Any], scheduled: list[Any]
) -> None:
    """RELEASE GATE. Completes "created, previewed, backfilled, compared, rolled back"."""
    private, _ = keypair
    response = client.post(
        "/v1/runs/backfill",
        json={
            "connection_id": str(world["connection_a"]),
            "resource": "records",
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-01-05T00:00:00Z",
        },
        headers=auth(private, world["admin_a"], world["org_a"]),
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["window_count"] == 4
    assert body["mapping_version"] == 4

    assert len(scheduled) == 1
    name, payload = scheduled[0]
    assert name == "Backfill"
    assert len(payload["windows"]) == 4
    assert payload["mapping_version"] == 4


def test_the_plan_is_returned_before_anything_runs(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    """ "This will re-read 366 days" is a decision, not a progress bar.

    A caller has to be able to see the size of what they are agreeing to at the
    moment they agree to it.
    """
    private, _ = keypair
    response = client.post(
        "/v1/runs/backfill",
        json={
            "connection_id": str(world["connection_a"]),
            "resource": "records",
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-02-01T00:00:00Z",
        },
        headers=auth(private, world["admin_a"], world["org_a"]),
    )
    body = response.json()
    assert body["window_count"] == 31
    assert len(body["windows"]) == 31
    assert body["windows"][0]["start"].startswith("2026-01-01")
    assert body["windows"][-1]["end"].startswith("2026-02-01")


def test_the_windows_have_no_gaps_and_no_overlaps(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    """A backfill that misses a day is worse than one that fails: nothing says so."""
    from itertools import pairwise

    private, _ = keypair
    response = client.post(
        "/v1/runs/backfill",
        json={
            "connection_id": str(world["connection_a"]),
            "resource": "records",
            "start": "2026-03-01T00:00:00Z",
            "end": "2026-03-10T00:00:00Z",
        },
        headers=auth(private, world["admin_a"], world["org_a"]),
    )
    windows = response.json()["windows"]
    for earlier, later in pairwise(windows):
        assert earlier["end"] == later["start"]


def test_an_absurd_range_is_refused(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    """An accidental decade should be refused, not quietly queued."""
    private, _ = keypair
    response = client.post(
        "/v1/runs/backfill",
        json={
            "connection_id": str(world["connection_a"]),
            "resource": "records",
            "start": "2016-01-01T00:00:00Z",
            "end": "2026-01-01T00:00:00Z",
        },
        headers=auth(private, world["admin_a"], world["org_a"]),
    )
    assert response.status_code == 422


def test_a_backwards_range_is_refused(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    private, _ = keypair
    response = client.post(
        "/v1/runs/backfill",
        json={
            "connection_id": str(world["connection_a"]),
            "resource": "records",
            "start": "2026-05-01T00:00:00Z",
            "end": "2026-04-01T00:00:00Z",
        },
        headers=auth(private, world["admin_a"], world["org_a"]),
    )
    assert response.status_code == 422


def test_a_backfill_uses_the_currently_active_mapping(
    client: TestClient, keypair: Any, world: dict[str, Any], owner_session: Session
) -> None:
    """This is how a correction reaches rows that were already written.

    A new version is applied, then history is re-read through it — nothing edits
    a canonical row in place.
    """
    private, _ = keypair
    owner_session.execute(
        text(
            "UPDATE mapping_versions SET is_active = false, applied_at = NULL "
            "WHERE connection_id = :c"
        ),
        {"c": world["connection_a"]},
    )
    owner_session.execute(
        text(
            "INSERT INTO mapping_versions (id, organization_id, connection_id, resource, "
            "version, column_map, target_table, is_active, applied_at) VALUES "
            "(gen_random_uuid(), :o, :c, 'records', 9, '{\"order_id\":\"id\"}', "
            "'stg_records', true, now())"
        ),
        {"o": world["org_a"], "c": world["connection_a"]},
    )
    owner_session.commit()

    response = client.post(
        "/v1/runs/backfill",
        json={
            "connection_id": str(world["connection_a"]),
            "resource": "records",
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-01-03T00:00:00Z",
        },
        headers=auth(private, world["admin_a"], world["org_a"]),
    )
    assert response.json()["mapping_version"] == 9


def test_a_backfill_with_no_active_mapping_is_refused(
    client: TestClient, keypair: Any, world: dict[str, Any], owner_session: Session
) -> None:
    """Running with no mapping would write nothing and report success.

    Which is the worst available combination: a green run and an empty table.
    """
    private, _ = keypair
    owner_session.execute(
        text(
            "UPDATE mapping_versions SET is_active = false, applied_at = NULL "
            "WHERE connection_id = :c"
        ),
        {"c": world["connection_a"]},
    )
    owner_session.commit()

    response = client.post(
        "/v1/runs/backfill",
        json={
            "connection_id": str(world["connection_a"]),
            "resource": "records",
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-01-03T00:00:00Z",
        },
        headers=auth(private, world["admin_a"], world["org_a"]),
    )
    assert response.status_code == 409
    assert "apply one first" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


def test_starting_a_run_records_it_and_schedules_it(
    client: TestClient, keypair: Any, world: dict[str, Any], scheduled: list[Any]
) -> None:
    """202, not 200. The run is accepted, not completed."""
    private, _ = keypair
    response = client.post(
        "/v1/runs",
        json={"connection_id": str(world["connection_a"]), "resources": ["records"]},
        headers=auth(private, world["admin_a"], world["org_a"]),
    )

    assert response.status_code == 202
    assert response.json()["outcome"] == "running"
    assert response.json()["records_quarantined"] == 0

    name, payload = scheduled[0]
    assert name == "ConnectorRun"
    # The run id is passed through, so the workflow updates the row the API
    # created rather than inventing a second one.
    assert payload["run_id"] == response.json()["id"]


def test_a_run_list_returns_only_the_callers_organization(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    private, _ = keypair
    mine = client.post(
        "/v1/runs",
        json={"connection_id": str(world["connection_a"]), "resources": ["records"]},
        headers=auth(private, world["admin_a"], world["org_a"]),
    )
    theirs = client.post(
        "/v1/runs",
        json={"connection_id": str(world["connection_b"]), "resources": ["records"]},
        headers=auth(private, world["admin_b"], world["org_b"]),
    )
    assert theirs.status_code == 202

    listed = client.get("/v1/runs", headers=auth(private, world["admin_a"], world["org_a"]))
    ids = {row["id"] for row in listed.json()}
    assert mine.json()["id"] in ids
    assert theirs.json()["id"] not in ids


def test_reading_another_organizations_run_is_404(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    """RELEASE GATE. 403 would confirm the id exists."""
    private, _ = keypair
    theirs = client.post(
        "/v1/runs",
        json={"connection_id": str(world["connection_b"]), "resources": ["records"]},
        headers=auth(private, world["admin_b"], world["org_b"]),
    )
    response = client.get(
        f"/v1/runs/{theirs.json()['id']}",
        headers=auth(private, world["admin_a"], world["org_a"]),
    )
    assert response.status_code == 404


def test_starting_a_run_on_another_organizations_connection_is_404(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    private, _ = keypair
    for path, body in (
        ("/v1/runs", {"connection_id": str(world["connection_b"]), "resources": ["records"]}),
        (
            "/v1/runs/backfill",
            {
                "connection_id": str(world["connection_b"]),
                "resource": "records",
                "start": "2026-01-01T00:00:00Z",
                "end": "2026-01-02T00:00:00Z",
            },
        ),
    ):
        response = client.post(
            path, json=body, headers=auth(private, world["admin_a"], world["org_a"])
        )
        assert response.status_code == 404, path


def test_a_manager_cannot_start_a_run(
    client: TestClient, keypair: Any, world: dict[str, Any], owner_session: Session
) -> None:
    private, _ = keypair
    manager = owner_session.execute(
        text("SELECT user_id FROM memberships WHERE organization_id = :o AND role = 'manager'"),
        {"o": world["org_a"]},
    ).scalar_one()
    response = client.post(
        "/v1/runs",
        json={"connection_id": str(world["connection_a"]), "resources": ["records"]},
        headers=auth(private, manager, world["org_a"]),
    )
    assert response.status_code == 403
    assert "source.manage" in response.json()["detail"]


def test_both_actions_are_audited(
    client: TestClient, keypair: Any, world: dict[str, Any], owner_session: Session
) -> None:
    private, _ = keypair
    headers = auth(private, world["admin_a"], world["org_a"])
    client.post(
        "/v1/runs",
        json={"connection_id": str(world["connection_a"]), "resources": ["records"]},
        headers=headers,
    )
    client.post(
        "/v1/runs/backfill",
        json={
            "connection_id": str(world["connection_a"]),
            "resource": "records",
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-01-02T00:00:00Z",
        },
        headers=headers,
    )

    actions = {
        row[0]
        for row in owner_session.execute(
            text("SELECT action FROM audit_events WHERE organization_id = :o"),
            {"o": world["org_a"]},
        ).all()
    }
    assert {"run.started", "backfill.started"} <= actions


def test_nothing_is_scheduled_when_the_request_is_refused(
    client: TestClient, keypair: Any, world: dict[str, Any], scheduled: list[Any]
) -> None:
    """A refusal must not be a partial success.

    Scheduling the workflow and then failing the request would leave work
    running that the caller believes never started.
    """
    private, _ = keypair
    client.post(
        "/v1/runs",
        json={"connection_id": str(world["connection_b"]), "resources": ["records"]},
        headers=auth(private, world["admin_a"], world["org_a"]),
    )
    assert scheduled == []
