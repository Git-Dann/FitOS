"""Mapping versions: create, preview, apply, compare, roll back.

The Phase C acceptance criterion says all five must work **through the API**, so
these drive the HTTP surface rather than the interpreter directly. The
interpreter has its own tests below the API ones, because the properties that
matter there — money arithmetic, schema drift, never raising on bad input — are
easier to state precisely at that level.
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
from fitos_api.mapping import (
    MappingSpec,
    UnknownTransformError,
    apply_mapping,
    diff_mappings,
    preview,
)
from fitos_api.models import Connection, Membership, User
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
def client(app_engine: Engine, keypair: Any) -> TestClient:
    _, public = keypair
    app = create_app(settings=Settings(environment=Environment.LOCAL))
    app.state.token_verifier = _StaticKeyVerifier(public)
    app.state.session_factory = sessionmaker(bind=app_engine, expire_on_commit=False)
    return TestClient(app)


@pytest.fixture
def world(owner_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]) -> dict[str, Any]:
    """An admin and a connection in each organization."""
    org_a, org_b = two_orgs
    out: dict[str, Any] = {"org_a": org_a, "org_b": org_b}
    for label, org in (("a", org_a), ("b", org_b)):
        user = User(email=f"map-{label}-{uuid.uuid4().hex[:8]}@example.com")
        owner_session.add(user)
        owner_session.flush()
        owner_session.add(Membership(organization_id=org, user_id=user.id, role="admin"))
        connection = Connection(
            organization_id=org,
            connector_key="generic_rest",
            connector_version=1,
            name=f"source-{label}",
            config={"base_url": "https://api.example"},
        )
        owner_session.add(connection)
        owner_session.flush()
        out[f"admin_{label}"] = user.id
        out[f"connection_{label}"] = connection.id
    owner_session.commit()
    return out


def _create(
    client: TestClient, private: Any, world: dict[str, Any], **overrides: Any
) -> dict[str, Any]:
    body = {
        "connection_id": str(world["connection_a"]),
        "resource": "records",
        "target_table": "stg_records",
        "column_map": {"order_id": "id", "amount_minor": "amount"},
        "required_columns": ["order_id"],
        "transforms": {"amount_minor": ["to_int"]},
    }
    body.update(overrides)
    response = client.post(
        "/v1/mappings", json=body, headers=auth(private, world["admin_a"], world["org_a"])
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


# ---------------------------------------------------------------------------
# The acceptance criterion, verb by verb
# ---------------------------------------------------------------------------


def test_a_version_can_be_created_previewed_applied_compared_and_rolled_back(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    """RELEASE GATE. The Phase C criterion, end to end through the API."""
    private, _ = keypair
    headers = auth(private, world["admin_a"], world["org_a"])

    first = _create(client, private, world)
    assert first["version"] == 1
    assert first["is_active"] is False, "a new version must be drafted, not live"

    previewed = client.post(
        f"/v1/mappings/{first['id']}/preview",
        json={"records": [{"id": "A-1", "amount": "1250"}, {"id": "", "amount": "x"}]},
        headers=headers,
    )
    assert previewed.status_code == 200
    assert previewed.json()["would_write"] == 1
    assert previewed.json()["would_quarantine"] == 1

    applied = client.post(f"/v1/mappings/{first['id']}/apply", headers=headers)
    assert applied.status_code == 200
    assert applied.json()["is_active"] is True

    second = _create(
        client,
        private,
        world,
        column_map={"order_id": "id", "amount_minor": "amount", "currency": "ccy"},
    )
    assert second["version"] == 2

    compared = client.get(f"/v1/mappings/{first['id']}/compare/{second['id']}", headers=headers)
    assert compared.status_code == 200
    assert compared.json()["added_columns"] == ["currency"]
    assert compared.json()["is_empty"] is False

    assert client.post(f"/v1/mappings/{second['id']}/apply", headers=headers).status_code == 200

    rolled = client.post(f"/v1/mappings/{first['id']}/rollback", headers=headers)
    assert rolled.status_code == 200
    assert rolled.json()["is_active"] is True
    assert rolled.json()["version"] == 1


def test_applying_deactivates_the_previous_version_atomically(
    client: TestClient, keypair: Any, world: dict[str, Any], owner_session: Session
) -> None:
    """Never two live mappings, and never zero.

    Two would mean two answers to "how was this row produced". Zero would
    silently drop whatever arrived during the switch.
    """
    private, _ = keypair
    headers = auth(private, world["admin_a"], world["org_a"])

    first = _create(client, private, world)
    second = _create(client, private, world, column_map={"order_id": "id"})

    client.post(f"/v1/mappings/{first['id']}/apply", headers=headers)
    client.post(f"/v1/mappings/{second['id']}/apply", headers=headers)

    active = owner_session.execute(
        text(
            "SELECT count(*) FROM mapping_versions "
            "WHERE connection_id = :c AND resource = 'records' AND is_active"
        ),
        {"c": world["connection_a"]},
    ).scalar_one()
    assert active == 1


def test_the_database_refuses_two_active_versions_even_if_the_service_tried(
    owner_session: Session, world: dict[str, Any]
) -> None:
    """Defence in depth. The partial unique index is the real guarantee."""
    from sqlalchemy.exc import IntegrityError

    for version in (1, 2):
        owner_session.execute(
            text(
                "INSERT INTO mapping_versions "
                "(id, organization_id, connection_id, resource, version, column_map, "
                " target_table, is_active, applied_at) "
                "VALUES (gen_random_uuid(), :o, :c, 'dup', :v, '{\"a\":\"b\"}', 'stg', "
                " true, now())"
            ),
            {"o": world["org_a"], "c": world["connection_a"], "v": version},
        ) if version == 1 else None

    with pytest.raises(IntegrityError, match="uq_mapping_one_active_per_resource"):
        owner_session.execute(
            text(
                "INSERT INTO mapping_versions "
                "(id, organization_id, connection_id, resource, version, column_map, "
                " target_table, is_active, applied_at) "
                "VALUES (gen_random_uuid(), :o, :c, 'dup', 2, '{\"a\":\"b\"}', 'stg', "
                " true, now())"
            ),
            {"o": world["org_a"], "c": world["connection_a"]},
        )
    owner_session.rollback()


def test_an_applied_version_cannot_be_edited(
    client: TestClient, keypair: Any, world: dict[str, Any], owner_session: Session
) -> None:
    """RELEASE GATE. Corrections happen forward.

    Editing the mapping that produced numbers people already acted on makes
    those numbers unreproducible, which is the one thing the version history
    exists to prevent.
    """
    # restrict_violation maps to IntegrityError, which is the right family: the
    # trigger is enforcing an integrity rule, not reporting a server fault.
    from sqlalchemy.exc import IntegrityError

    private, _ = keypair
    version = _create(client, private, world)
    client.post(
        f"/v1/mappings/{version['id']}/apply",
        headers=auth(private, world["admin_a"], world["org_a"]),
    )

    with pytest.raises(IntegrityError, match="cannot be edited"):
        owner_session.execute(
            text('UPDATE mapping_versions SET column_map = \'{"x":"y"}\' WHERE id = :i'),
            {"i": version["id"]},
        )
    owner_session.rollback()


def test_rolling_back_does_not_delete_the_newer_version(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    """Rows produced by version 2 must stay explicable after rolling back to 1."""
    private, _ = keypair
    headers = auth(private, world["admin_a"], world["org_a"])

    first = _create(client, private, world)
    second = _create(client, private, world, column_map={"order_id": "id"})
    client.post(f"/v1/mappings/{first['id']}/apply", headers=headers)
    client.post(f"/v1/mappings/{second['id']}/apply", headers=headers)
    client.post(f"/v1/mappings/{first['id']}/rollback", headers=headers)

    still_there = client.get(f"/v1/mappings/{second['id']}", headers=headers)
    assert still_there.status_code == 200
    assert still_there.json()["version"] == 2
    assert still_there.json()["is_active"] is False


def test_rolling_forward_is_refused_and_named(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    """ "We rolled back" and "we applied a new mapping" are different events."""
    private, _ = keypair
    headers = auth(private, world["admin_a"], world["org_a"])

    first = _create(client, private, world)
    second = _create(client, private, world, column_map={"order_id": "id"})
    client.post(f"/v1/mappings/{first['id']}/apply", headers=headers)

    response = client.post(f"/v1/mappings/{second['id']}/rollback", headers=headers)
    assert response.status_code == 409
    assert "use apply" in response.json()["detail"]


def test_every_transition_is_audited(
    client: TestClient, keypair: Any, world: dict[str, Any], owner_session: Session
) -> None:
    private, _ = keypair
    headers = auth(private, world["admin_a"], world["org_a"])
    first = _create(client, private, world)
    second = _create(client, private, world, column_map={"order_id": "id"})
    client.post(f"/v1/mappings/{first['id']}/apply", headers=headers)
    client.post(f"/v1/mappings/{second['id']}/apply", headers=headers)
    client.post(f"/v1/mappings/{first['id']}/rollback", headers=headers)

    actions = {
        row[0]
        for row in owner_session.execute(
            text("SELECT action FROM audit_events WHERE organization_id = :o"),
            {"o": world["org_a"]},
        ).all()
    }
    assert {"mapping.created", "mapping.applied", "mapping.rolled_back"} <= actions


def test_an_unknown_transform_is_refused_at_save_time(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    """A typo that quietly does nothing produces plausible wrong numbers."""
    private, _ = keypair
    response = client.post(
        "/v1/mappings",
        json={
            "connection_id": str(world["connection_a"]),
            "resource": "records",
            "target_table": "stg_records",
            "column_map": {"a": "b"},
            "transforms": {"a": ["definitely_not_a_transform"]},
        },
        headers=auth(private, world["admin_a"], world["org_a"]),
    )
    assert response.status_code == 422
    assert "unknown transform" in response.json()["detail"]


def test_preview_has_no_side_effect(
    client: TestClient, keypair: Any, world: dict[str, Any], owner_session: Session
) -> None:
    """A preview with a side effect is not a preview."""
    private, _ = keypair
    headers = auth(private, world["admin_a"], world["org_a"])
    version = _create(client, private, world)

    before = owner_session.execute(text("SELECT count(*) FROM connector_runs")).scalar_one()
    client.post(
        f"/v1/mappings/{version['id']}/preview",
        json={"records": [{"id": "A-1", "amount": "1"}]},
        headers=headers,
    )
    after = owner_session.execute(text("SELECT count(*) FROM connector_runs")).scalar_one()

    assert before == after
    assert client.get(f"/v1/mappings/{version['id']}", headers=headers).json()["is_active"] is False


# ---------------------------------------------------------------------------
# Cross-tenant
# ---------------------------------------------------------------------------


def test_a_mapping_list_returns_only_the_callers_organization(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    private, _ = keypair
    mine = _create(client, private, world)
    theirs = client.post(
        "/v1/mappings",
        json={
            "connection_id": str(world["connection_b"]),
            "resource": "records",
            "target_table": "stg_records",
            "column_map": {"order_id": "id"},
        },
        headers=auth(private, world["admin_b"], world["org_b"]),
    )
    assert theirs.status_code == 201

    listed = client.get("/v1/mappings", headers=auth(private, world["admin_a"], world["org_a"]))
    ids = {row["id"] for row in listed.json()}
    assert ids == {mine["id"]}


def test_reading_another_organizations_mapping_is_404(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    """RELEASE GATE. 403 would confirm the id exists."""
    private, _ = keypair
    theirs = client.post(
        "/v1/mappings",
        json={
            "connection_id": str(world["connection_b"]),
            "resource": "records",
            "target_table": "stg_records",
            "column_map": {"order_id": "id"},
        },
        headers=auth(private, world["admin_b"], world["org_b"]),
    )
    response = client.get(
        f"/v1/mappings/{theirs.json()['id']}",
        headers=auth(private, world["admin_a"], world["org_a"]),
    )
    assert response.status_code == 404


def test_applying_another_organizations_mapping_is_404(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    private, _ = keypair
    theirs = client.post(
        "/v1/mappings",
        json={
            "connection_id": str(world["connection_b"]),
            "resource": "records",
            "target_table": "stg_records",
            "column_map": {"order_id": "id"},
        },
        headers=auth(private, world["admin_b"], world["org_b"]),
    )
    for verb in ("apply", "rollback"):
        response = client.post(
            f"/v1/mappings/{theirs.json()['id']}/{verb}",
            headers=auth(private, world["admin_a"], world["org_a"]),
        )
        assert response.status_code == 404, verb


def test_creating_a_mapping_for_another_organizations_connection_is_404(
    client: TestClient, keypair: Any, world: dict[str, Any]
) -> None:
    """The connection id is a request field; RLS is what makes it safe."""
    private, _ = keypair
    response = client.post(
        "/v1/mappings",
        json={
            "connection_id": str(world["connection_b"]),
            "resource": "records",
            "target_table": "stg_records",
            "column_map": {"order_id": "id"},
        },
        headers=auth(private, world["admin_a"], world["org_a"]),
    )
    assert response.status_code == 404


def test_a_manager_cannot_manage_mappings(
    client: TestClient, keypair: Any, world: dict[str, Any], owner_session: Session
) -> None:
    private, _ = keypair
    manager = owner_session.execute(
        text("SELECT user_id FROM memberships WHERE organization_id = :o AND role = 'manager'"),
        {"o": world["org_a"]},
    ).scalar_one()
    response = client.get("/v1/mappings", headers=auth(private, manager, world["org_a"]))
    assert response.status_code == 403
    assert "mapping.manage" in response.json()["detail"]


# ---------------------------------------------------------------------------
# The interpreter
# ---------------------------------------------------------------------------


def _spec(**overrides: Any) -> MappingSpec:
    base: dict[str, Any] = {
        "version": 1,
        "target_table": "stg_records",
        "column_map": {"order_id": "id", "amount_minor": "amount"},
        "required_columns": ("order_id",),
        "transforms": {"amount_minor": ["to_int"]},
    }
    base.update(overrides)
    return MappingSpec(**base)


def test_a_clean_record_maps_to_a_row() -> None:
    result = apply_mapping(_spec(), {"id": "A-1", "amount": "1250"})
    assert result.ok
    assert result.row == {"order_id": "A-1", "amount_minor": 1250}


def test_bad_input_produces_reasons_rather_than_an_exception() -> None:
    """An exception here aborts a 200,000-record run because one row was wrong."""
    result = apply_mapping(_spec(), {"id": "A-1", "amount": "not-a-number"})
    assert not result.ok
    assert {r.flag.value for r in result.reasons} == {"type_coerced"}


def test_a_missing_source_column_is_reported_as_schema_drift() -> None:
    """Drift and a missing value have different fixes.

    Conflating them sends whoever is on call to correct data when the source
    changed shape, or the reverse.
    """
    result = apply_mapping(_spec(), {"id": "A-1"})
    flags = {r.flag.value for r in result.reasons}
    assert "schema_drift" in flags


def test_money_conversion_does_not_go_through_a_float() -> None:
    """19.99 becomes 1999, not 1998.

    Binary floating point cannot represent 19.99, so `int(19.99 * 100)` is
    1998 — a penny lost per transaction, silently, on every row.
    """
    spec = _spec(
        column_map={"amount_minor": "amount"},
        required_columns=(),
        transforms={"amount_minor": ["to_minor_units"]},
    )
    for given, expected in (("19.99", 1999), ("0.07", 7), ("1234.56", 123456), ("8.10", 810)):
        result = apply_mapping(spec, {"amount": given})
        assert result.ok, result.reasons
        assert result.row == {"amount_minor": expected}, given


def test_transforms_are_a_closed_set() -> None:
    """An expression language here would be remote code execution by config."""
    with pytest.raises(UnknownTransformError, match="unknown transform"):
        _spec(transforms={"amount_minor": ["__import__('os').system"]})


def test_a_required_column_that_maps_to_nothing_is_quarantined() -> None:
    result = apply_mapping(_spec(), {"id": "", "amount": "1"})
    assert not result.ok
    assert any(r.flag.value == "missing_required" for r in result.reasons)


def test_a_row_is_either_written_or_rejected_never_both() -> None:
    """A partial row with a reason attached is how half-mapped data ships."""
    for payload in ({"id": "A", "amount": "1"}, {"id": "", "amount": "x"}, {}):
        result = apply_mapping(_spec(), payload)
        assert (result.row is None) != (result.reasons == ())


def test_the_same_mapping_and_record_always_produce_the_same_row() -> None:
    """Evidence has to stay reproducible long after the mapping has moved on."""
    spec = _spec()
    payload = {"id": "A-1", "amount": "1250"}
    assert apply_mapping(spec, payload).row == apply_mapping(spec, payload).row


def test_a_diff_names_what_changed_rather_than_which_lines() -> None:
    before = _spec()
    after = _spec(
        column_map={"order_id": "order_number", "amount_minor": "amount", "currency": "ccy"}
    )
    diff = diff_mappings(before, after)

    assert diff.added_columns == ("currency",)
    assert diff.changed_columns == (("order_id", "id", "order_number"),)
    assert diff.removed_columns == ()
    assert not diff.is_empty


def test_comparing_a_version_with_itself_is_empty() -> None:
    assert diff_mappings(_spec(), _spec()).is_empty


def test_preview_counts_every_record_but_returns_a_sample() -> None:
    """The counts have to be exact even when the returned rows are truncated."""
    records = [(str(i), {"id": f"A-{i}", "amount": "1"}) for i in range(100)]
    records += [(f"bad-{i}", {"id": "", "amount": "x"}) for i in range(5)]

    result = preview(_spec(), records, limit=10)
    assert result.sampled == 105
    assert result.would_write == 100
    assert result.would_quarantine == 5
    assert len(result.rows) == 10
    assert round(result.rejection_rate, 4) == round(5 / 105, 4)
