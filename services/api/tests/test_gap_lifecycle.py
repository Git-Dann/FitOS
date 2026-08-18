"""The gap lifecycle at the HTTP boundary.

Three things are proved here that cannot be proved by reading the transition
table: every illegal pair is actually refused, exposure never reaches a token
that may not see it, and a concurrent edit loses loudly rather than silently.

The exposure tests are the ones worth being fussy about. The acceptance
criterion is "exposure fields are absent from a frontline token's payload" —
absent, not null and not zero. A null field on a ledger where most gaps carry a
number still says "there is a figure here you may not see", and a masked field
means the number crossed the wire to a client that chose not to draw it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from conftest import auth, requires_db
from fastapi.testclient import TestClient
from fitos_api.gaps.lifecycle import (
    DISMISSAL_REASONS,
    TRANSITIONS,
    GapStatus,
    legal_transitions,
)
from sqlalchemy import text
from sqlalchemy.orm import Session

pytestmark = requires_db

NOW = datetime(2026, 8, 2, tzinfo=UTC)


def _gap_row(org_id: uuid.UUID, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": uuid.uuid4(),
        "organization_id": org_id,
        "pack_key": "retail_omnichannel",
        "gap_type": "stock_truth_mismatch",
        "title": "Stock records and counts disagree at store-1",
        "summary": "40% of checks disagreed.",
        "scope_type": "location",
        "scope_id": "store-1",
        "metric_definition_id": uuid.uuid4(),
        "metric_version": 1,
        "observed_value": 0.40,
        "expected_value": 0.02,
        "absolute_delta": 0.38,
        "percentage_delta": 19.0,
        "unit": "ratio",
        "currency": "GBP",
        "exposure_low": 6000,
        "exposure_base": 8800,
        "exposure_high": 12400,
        "confidence_score": 0.82,
        "confidence_band": "high",
        "severity": "high",
        "status": "detected",
        "owner_id": None,
        "first_seen_at": NOW - timedelta(days=1),
        "last_seen_at": NOW,
        "as_of_at": NOW,
        "data_freshness_seconds": 3600,
        "rule_id": uuid.uuid4(),
        "rule_version": 1,
        "detector_run_id": uuid.uuid4(),
        "assumptions": '[{"key": "unit_margin_minor", "statement": "s", "value": "150..310"}]',
        "evidence_refs": '[{"metric_key": "stock_discrepancy_rate", "metric_version": 1}]',
        "recommended_actions": "[]",
        "reason_codes": '["source_disagreement"]',
        "dedupe_key": uuid.uuid4().hex,
        "lifecycle_version": 1,
    }
    row.update(overrides)
    return row


INSERT_GAP = text(
    """
    INSERT INTO gaps (
      id, organization_id, pack_key, gap_type, title, summary, scope_type, scope_id,
      metric_definition_id, metric_version, observed_value, expected_value,
      absolute_delta, percentage_delta, unit, currency,
      exposure_low, exposure_base, exposure_high, confidence_score, confidence_band,
      severity, status, owner_id, first_seen_at, last_seen_at, as_of_at,
      data_freshness_seconds, rule_id, rule_version, detector_run_id,
      assumptions, evidence_refs, recommended_actions, reason_codes, dedupe_key,
      lifecycle_version
    ) VALUES (
      :id, :organization_id, :pack_key, :gap_type, :title, :summary, :scope_type, :scope_id,
      :metric_definition_id, :metric_version, :observed_value, :expected_value,
      :absolute_delta, :percentage_delta, :unit, :currency,
      :exposure_low, :exposure_base, :exposure_high, :confidence_score, :confidence_band,
      :severity, :status, :owner_id, :first_seen_at, :last_seen_at, :as_of_at,
      :data_freshness_seconds, :rule_id, :rule_version, :detector_run_id,
      CAST(:assumptions AS jsonb), CAST(:evidence_refs AS jsonb),
      CAST(:recommended_actions AS jsonb), CAST(:reason_codes AS jsonb), :dedupe_key,
      :lifecycle_version
    )
    """
)


@pytest.fixture
def gaps(owner_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]) -> dict[str, Any]:
    """One gap in each organization, plus the membership ids to act as."""
    org_a, org_b = two_orgs
    row_a = _gap_row(org_a)
    row_b = _gap_row(org_b)
    owner_session.execute(INSERT_GAP, row_a)
    owner_session.execute(INSERT_GAP, row_b)

    members = owner_session.execute(
        text(
            "SELECT organization_id, id, user_id, role FROM memberships "
            "WHERE organization_id = ANY(:o)"
        ),
        {"o": [org_a, org_b]},
    ).all()
    by_org = {r[0]: r for r in members}
    owner_session.commit()

    return {
        "org_a": org_a,
        "org_b": org_b,
        "gap_a": row_a["id"],
        "gap_b": row_b["id"],
        "user_a": by_org[org_a][2],
        "user_b": by_org[org_b][2],
        "mem_a": by_org[org_a][1],
        "mem_b": by_org[org_b][1],
    }


def set_role(owner_session: Session, membership_id: uuid.UUID, role: str) -> None:
    """Authority comes from the membership row, not the token (ADR 0009)."""
    owner_session.execute(
        text("UPDATE memberships SET role = :r WHERE id = :i"), {"r": role, "i": membership_id}
    )
    owner_session.commit()


def set_status(owner_session: Session, gap_id: uuid.UUID, status: str, **extra: Any) -> None:
    columns = ", ".join(f"{k} = :{k}" for k in extra)
    sql = f"UPDATE gaps SET status = :s{', ' + columns if extra else ''} WHERE id = :i"  # noqa: S608
    owner_session.execute(text(sql), {"s": status, "i": gap_id, **extra})
    owner_session.commit()


# ---------------------------------------------------------------------------
# The transition table
# ---------------------------------------------------------------------------


def test_every_status_appears_in_the_transition_table() -> None:
    assert set(TRANSITIONS) == set(GapStatus)


def test_terminal_statuses_have_no_outgoing_transitions() -> None:
    """Reopening is a new gap, not an edge. Modelling it as one would let a
    detector re-firing resurrect closed work."""
    assert legal_transitions(GapStatus.RESOLVED) == frozenset()
    assert legal_transitions(GapStatus.DISMISSED) == frozenset()


def test_the_table_enumerates_exactly_the_documented_edges() -> None:
    """Twenty-one legal pairs out of forty-nine possible ones means twenty-eight
    ways to be wrong, and nobody spots all of them by reading."""
    legal = {(a.value, b.value) for a, targets in TRANSITIONS.items() for b in targets}
    assert legal == {
        ("detected", "triaged"),
        ("detected", "dismissed"),
        ("triaged", "investigating"),
        ("triaged", "dismissed"),
        ("investigating", "actioned"),
        ("investigating", "dismissed"),
        ("actioned", "validating"),
        ("actioned", "dismissed"),
        ("validating", "resolved"),
        ("validating", "dismissed"),
    }


def test_there_is_no_backward_edge() -> None:
    """A gap moved on prematurely is corrected by dismissing it and letting the
    detector raise it again, which leaves a record. A silent step backwards
    leaves none."""
    order = [
        GapStatus.DETECTED,
        GapStatus.TRIAGED,
        GapStatus.INVESTIGATING,
        GapStatus.ACTIONED,
        GapStatus.VALIDATING,
    ]
    for i, source in enumerate(order):
        for earlier in order[:i]:
            assert earlier not in TRANSITIONS[source], f"{source} can go back to {earlier}"


# ---------------------------------------------------------------------------
# Transitions over HTTP
# ---------------------------------------------------------------------------


def test_a_legal_transition_succeeds_and_bumps_the_version(
    client: TestClient, keypair: Any, gaps: dict[str, Any], owner_session: Session
) -> None:
    private, _ = keypair
    headers = auth(private, gaps["user_a"], gaps["org_a"])
    client.post(
        f"/v1/gaps/{gaps['gap_a']}/assign",
        json={"owner_id": str(gaps["mem_a"]), "expected_version": 1},
        headers=headers,
    )

    r = client.post(
        f"/v1/gaps/{gaps['gap_a']}/transition",
        json={"to_status": "triaged", "expected_version": 2},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "triaged"
    assert r.json()["lifecycle_version"] == 3


def test_an_illegal_transition_is_refused_with_the_legal_ones(
    client: TestClient, keypair: Any, gaps: dict[str, Any]
) -> None:
    private, _ = keypair
    r = client.post(
        f"/v1/gaps/{gaps['gap_a']}/transition",
        json={"to_status": "resolved", "expected_version": 1},
        headers=auth(private, gaps["user_a"], gaps["org_a"]),
    )
    assert r.status_code == 422
    assert "not a legal transition" in r.json()["detail"]
    assert "triaged" in r.json()["detail"], "the refusal should say what is reachable"


def test_a_terminal_gap_refuses_every_transition(
    client: TestClient, keypair: Any, gaps: dict[str, Any], owner_session: Session
) -> None:
    set_status(
        owner_session,
        gaps["gap_a"],
        "dismissed",
        dismissed_at=NOW,
        dismissal_reason_code="duplicate",
        dismissal_note="already tracked",
    )
    private, _ = keypair
    for target in ("triaged", "investigating", "resolved"):
        r = client.post(
            f"/v1/gaps/{gaps['gap_a']}/transition",
            json={"to_status": target, "expected_version": 1},
            headers=auth(private, gaps["user_a"], gaps["org_a"]),
        )
        assert r.status_code == 422
        assert "terminal" in r.json()["detail"]


def test_a_stale_version_loses_loudly(
    client: TestClient, keypair: Any, gaps: dict[str, Any]
) -> None:
    """Two people triaging from a stale list must not silently overwrite each
    other; the second is told what the current version is."""
    private, _ = keypair
    headers = auth(private, gaps["user_a"], gaps["org_a"])
    client.post(
        f"/v1/gaps/{gaps['gap_a']}/assign",
        json={"owner_id": str(gaps["mem_a"]), "expected_version": 1},
        headers=headers,
    )

    r = client.post(
        f"/v1/gaps/{gaps['gap_a']}/transition",
        json={"to_status": "triaged", "expected_version": 1},
        headers=headers,
    )
    assert r.status_code == 409
    assert "version 2" in r.json()["detail"]


def test_triage_without_an_owner_is_refused(
    client: TestClient, keypair: Any, gaps: dict[str, Any]
) -> None:
    """A triaged gap nobody owns is an unread gap with a different label."""
    private, _ = keypair
    r = client.post(
        f"/v1/gaps/{gaps['gap_a']}/transition",
        json={"to_status": "triaged", "expected_version": 1},
        headers=auth(private, gaps["user_a"], gaps["org_a"]),
    )
    assert r.status_code == 422
    assert "owner" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Dismissal
# ---------------------------------------------------------------------------


def test_dismissal_needs_a_reason_code_and_a_note(
    client: TestClient, keypair: Any, gaps: dict[str, Any]
) -> None:
    private, _ = keypair
    headers = auth(private, gaps["user_a"], gaps["org_a"])

    no_code = client.post(
        f"/v1/gaps/{gaps['gap_a']}/transition",
        json={"to_status": "dismissed", "expected_version": 1, "note": "n"},
        headers=headers,
    )
    assert no_code.status_code == 422

    no_note = client.post(
        f"/v1/gaps/{gaps['gap_a']}/transition",
        json={"to_status": "dismissed", "expected_version": 1, "reason_code": "duplicate"},
        headers=headers,
    )
    assert no_note.status_code == 422
    assert "note" in no_note.json()["detail"]


def test_a_blank_note_does_not_count_as_a_note(
    client: TestClient, keypair: Any, gaps: dict[str, Any]
) -> None:
    private, _ = keypair
    r = client.post(
        f"/v1/gaps/{gaps['gap_a']}/transition",
        json={
            "to_status": "dismissed",
            "expected_version": 1,
            "reason_code": "duplicate",
            "note": "   ",
        },
        headers=auth(private, gaps["user_a"], gaps["org_a"]),
    )
    assert r.status_code == 422


def test_an_unknown_reason_code_is_refused(
    client: TestClient, keypair: Any, gaps: dict[str, Any]
) -> None:
    private, _ = keypair
    r = client.post(
        f"/v1/gaps/{gaps['gap_a']}/transition",
        json={
            "to_status": "dismissed",
            "expected_version": 1,
            "reason_code": "because_i_said_so",
            "note": "n",
        },
        headers=auth(private, gaps["user_a"], gaps["org_a"]),
    )
    assert r.status_code == 422


def test_a_complete_dismissal_succeeds_and_records_both_fields(
    client: TestClient, keypair: Any, gaps: dict[str, Any]
) -> None:
    private, _ = keypair
    r = client.post(
        f"/v1/gaps/{gaps['gap_a']}/transition",
        json={
            "to_status": "dismissed",
            "expected_version": 1,
            "reason_code": "known_and_accepted",
            "note": "Seasonal stock movement at this site; reviewed with the area manager.",
        },
        headers=auth(private, gaps["user_a"], gaps["org_a"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "dismissed"
    assert body["dismissal_reason_code"] == "known_and_accepted"
    assert body["dismissal_note"].startswith("Seasonal")
    assert body["dismissed_at"] is not None


def test_a_frontline_caller_cannot_dismiss(
    client: TestClient, keypair: Any, gaps: dict[str, Any], owner_session: Session
) -> None:
    """Dismissal is how a ledger gets quietly emptied, so it has its own
    capability rather than riding on gap.transition."""
    set_role(owner_session, gaps["mem_a"], "frontline")
    private, _ = keypair
    r = client.post(
        f"/v1/gaps/{gaps['gap_a']}/transition",
        json={
            "to_status": "dismissed",
            "expected_version": 1,
            "reason_code": "duplicate",
            "note": "n",
        },
        headers=auth(private, gaps["user_a"], gaps["org_a"]),
    )
    assert r.status_code == 403


def test_dismissal_needs_its_own_capability_not_just_gap_transition(
    client: TestClient, keypair: Any, gaps: dict[str, Any], owner_session: Session
) -> None:
    """The discriminating case for the separate capability.

    A caller holding neither capability is refused either way, so testing with a
    plain frontline role cannot tell `gap.dismiss` from `gap.transition` — it
    passes just as happily when dismissal is mapped to the wrong one. This uses
    the grant mechanism to build the one caller that distinguishes them: a
    frontline membership granted `gap.transition` and nothing else, which may
    advance a gap and may not empty it.
    """
    set_role(owner_session, gaps["mem_a"], "frontline")
    owner_session.execute(
        text("UPDATE memberships SET granted_capabilities = CAST(:g AS jsonb) WHERE id = :i"),
        {"g": '["gap.transition", "gap.assign"]', "i": gaps["mem_a"]},
    )
    owner_session.commit()

    private, _ = keypair
    headers = auth(private, gaps["user_a"], gaps["org_a"])

    assigned = client.post(
        f"/v1/gaps/{gaps['gap_a']}/assign",
        json={"owner_id": str(gaps["mem_a"]), "expected_version": 1},
        headers=headers,
    )
    assert assigned.status_code == 200, assigned.text

    advanced = client.post(
        f"/v1/gaps/{gaps['gap_a']}/transition",
        json={"to_status": "triaged", "expected_version": 2},
        headers=headers,
    )
    assert advanced.status_code == 200, "gap.transition should allow advancing the gap"

    dismissed = client.post(
        f"/v1/gaps/{gaps['gap_a']}/transition",
        json={
            "to_status": "dismissed",
            "expected_version": 3,
            "reason_code": "duplicate",
            "note": "Already tracked.",
        },
        headers=headers,
    )
    assert dismissed.status_code == 403, "gap.transition must not confer gap.dismiss"


def test_only_dismissal_maps_to_the_dismiss_capability() -> None:
    """Structural companion: every other destination rides on gap.transition."""
    from fitos_api.capabilities import Capability
    from fitos_api.gaps.lifecycle import TRANSITION_CAPABILITY

    assert TRANSITION_CAPABILITY[GapStatus.DISMISSED] is Capability.GAP_DISMISS
    others = {s: c for s, c in TRANSITION_CAPABILITY.items() if s is not GapStatus.DISMISSED}
    assert set(others.values()) == {Capability.GAP_TRANSITION}


def test_the_dismissal_reasons_are_served_not_duplicated_in_the_client(
    client: TestClient, keypair: Any, gaps: dict[str, Any]
) -> None:
    private, _ = keypair
    r = client.get(
        "/v1/gaps/meta/dismissal-reasons",
        headers=auth(private, gaps["user_a"], gaps["org_a"]),
    )
    assert r.status_code == 200
    assert r.json() == list(DISMISSAL_REASONS)


# ---------------------------------------------------------------------------
# Resolution needs an outcome
# ---------------------------------------------------------------------------


def test_resolution_without_an_outcome_is_refused(
    client: TestClient, keypair: Any, gaps: dict[str, Any], owner_session: Session
) -> None:
    """Recording no measurable change is an outcome. Recording nothing is not."""
    set_status(owner_session, gaps["gap_a"], "validating")
    private, _ = keypair
    r = client.post(
        f"/v1/gaps/{gaps['gap_a']}/transition",
        json={"to_status": "resolved", "expected_version": 1},
        headers=auth(private, gaps["user_a"], gaps["org_a"]),
    )
    assert r.status_code == 422
    assert "outcome" in r.json()["detail"]


def test_no_measurable_change_is_a_first_class_outcome(
    client: TestClient, keypair: Any, gaps: dict[str, Any], owner_session: Session
) -> None:
    """As easy to record as a positive one — otherwise the ledger becomes a
    success-reporting instrument."""
    set_status(owner_session, gaps["gap_a"], "validating")
    private, _ = keypair
    headers = auth(private, gaps["user_a"], gaps["org_a"])

    outcome = client.post(
        f"/v1/gaps/{gaps['gap_a']}/outcomes",
        json={
            "measurement_window_start": "2026-08-02T00:00:00Z",
            "measurement_window_end": "2026-08-09T00:00:00Z",
            "metric_definition_id": str(uuid.uuid4()),
            "metric_version": 1,
            "value_before": 0.40,
            "value_after": 0.40,
            "method": "observed",
            "notes": "No measurable change after the recount.",
        },
        headers=headers,
    )
    assert outcome.status_code == 201, outcome.text
    assert outcome.json()["delta"] == 0.0

    resolved = client.post(
        f"/v1/gaps/{gaps['gap_a']}/transition",
        json={
            "to_status": "resolved",
            "expected_version": 1,
            "outcome_id": outcome.json()["id"],
        },
        headers=headers,
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["outcome_id"] == outcome.json()["id"]


def test_the_delta_is_computed_not_accepted(
    client: TestClient, keypair: Any, gaps: dict[str, Any]
) -> None:
    """A delta that disagrees with its own before and after is the easiest way
    to misreport a result, and it would be invisible in the row."""
    private, _ = keypair
    r = client.post(
        f"/v1/gaps/{gaps['gap_a']}/outcomes",
        json={
            "measurement_window_start": "2026-08-02T00:00:00Z",
            "measurement_window_end": "2026-08-09T00:00:00Z",
            "metric_definition_id": str(uuid.uuid4()),
            "metric_version": 1,
            "value_before": 0.40,
            "value_after": 0.10,
            "method": "pre_post",
            "delta": -999.0,
        },
        headers=auth(private, gaps["user_a"], gaps["org_a"]),
    )
    assert r.status_code == 201, r.text
    assert r.json()["delta"] == pytest.approx(-0.30)


def test_an_unknown_outcome_method_is_refused_by_the_database(
    client: TestClient, keypair: Any, gaps: dict[str, Any]
) -> None:
    """Only a controlled_test outcome may carry causal language, so the method
    is a closed set rather than free text."""
    private, _ = keypair
    with pytest.raises(Exception, match="ck_outcome_method"):
        client.post(
            f"/v1/gaps/{gaps['gap_a']}/outcomes",
            json={
                "measurement_window_start": "2026-08-02T00:00:00Z",
                "measurement_window_end": "2026-08-09T00:00:00Z",
                "metric_definition_id": str(uuid.uuid4()),
                "metric_version": 1,
                "value_before": 1.0,
                "value_after": 2.0,
                "method": "it_obviously_worked",
            },
            headers=auth(private, gaps["user_a"], gaps["org_a"]),
        )


# ---------------------------------------------------------------------------
# Exposure is withheld server-side
# ---------------------------------------------------------------------------


EXPOSURE_KEYS = ("exposure_low", "exposure_base", "exposure_high", "currency", "assumptions")


def test_a_frontline_payload_has_no_exposure_fields_at_all(
    client: TestClient, keypair: Any, gaps: dict[str, Any], owner_session: Session
) -> None:
    """ACCEPTANCE: absent, not null and not zero.

    A null field on a ledger where most gaps carry a number still says "there is
    a figure here you may not see", and masking in the client means the number
    crossed the wire.
    """
    set_role(owner_session, gaps["mem_a"], "frontline")
    private, _ = keypair
    r = client.get(
        f"/v1/gaps/{gaps['gap_a']}",
        headers=auth(private, gaps["user_a"], gaps["org_a"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    for key in EXPOSURE_KEYS:
        assert key not in body, f"{key} reached a frontline caller"


def test_the_exposure_numbers_are_nowhere_in_the_frontline_response_body(
    client: TestClient, keypair: Any, gaps: dict[str, Any], owner_session: Session
) -> None:
    """Checks the raw text, not the parsed keys: a renamed field or a nested
    copy would pass the key check and still leak the figure."""
    set_role(owner_session, gaps["mem_a"], "frontline")
    private, _ = keypair
    r = client.get(
        f"/v1/gaps/{gaps['gap_a']}",
        headers=auth(private, gaps["user_a"], gaps["org_a"]),
    )
    for figure in ("6000", "8800", "12400", "unit_margin_minor"):
        assert figure not in r.text, f"{figure} appears in a frontline payload"


def test_a_manager_receives_the_exposure(
    client: TestClient, keypair: Any, gaps: dict[str, Any]
) -> None:
    private, _ = keypair
    body = client.get(
        f"/v1/gaps/{gaps['gap_a']}",
        headers=auth(private, gaps["user_a"], gaps["org_a"]),
    ).json()
    assert body["exposure_base"] == 8800
    assert body["currency"] == "GBP"
    assert body["assumptions"]


def test_the_list_endpoint_filters_exposure_too(
    client: TestClient, keypair: Any, gaps: dict[str, Any], owner_session: Session
) -> None:
    """A second serialisation path is how the rule gets broken: the detail route
    filters and the list route quietly does not."""
    set_role(owner_session, gaps["mem_a"], "frontline")
    private, _ = keypair
    r = client.get("/v1/gaps", headers=auth(private, gaps["user_a"], gaps["org_a"]))
    assert r.status_code == 200
    assert r.json()
    for row in r.json():
        for key in EXPOSURE_KEYS:
            assert key not in row


def test_a_granted_frontline_caller_does_receive_exposure(
    client: TestClient, keypair: Any, gaps: dict[str, Any], owner_session: Session
) -> None:
    """The brief's exception: frontline sees no modelled money "unless the role
    has permission and a direct need". That is a capability grant on the
    membership, not a code change and not a UI condition."""
    set_role(owner_session, gaps["mem_a"], "frontline")
    owner_session.execute(
        text("UPDATE memberships SET granted_capabilities = CAST(:g AS jsonb) WHERE id = :i"),
        {"g": '["gap.view_exposure"]', "i": gaps["mem_a"]},
    )
    owner_session.commit()

    private, _ = keypair
    body = client.get(
        f"/v1/gaps/{gaps['gap_a']}",
        headers=auth(private, gaps["user_a"], gaps["org_a"]),
    ).json()
    assert body["exposure_base"] == 8800


# ---------------------------------------------------------------------------
# Cross-tenant — the release gate
# ---------------------------------------------------------------------------


def test_the_list_returns_only_the_callers_gaps(
    client: TestClient, keypair: Any, gaps: dict[str, Any]
) -> None:
    private, _ = keypair
    r = client.get("/v1/gaps", headers=auth(private, gaps["user_a"], gaps["org_a"]))
    returned = {row["id"] for row in r.json()}
    assert returned == {str(gaps["gap_a"])}
    assert str(gaps["gap_b"]) not in returned


def test_reading_another_organizations_gap_is_404_not_403(
    client: TestClient, keypair: Any, gaps: dict[str, Any]
) -> None:
    """RELEASE GATE. 403 would confirm the id exists somewhere."""
    private, _ = keypair
    r = client.get(
        f"/v1/gaps/{gaps['gap_b']}", headers=auth(private, gaps["user_a"], gaps["org_a"])
    )
    assert r.status_code == 404


def test_transitioning_another_organizations_gap_is_404_not_403(
    client: TestClient, keypair: Any, gaps: dict[str, Any]
) -> None:
    private, _ = keypair
    r = client.post(
        f"/v1/gaps/{gaps['gap_b']}/transition",
        json={"to_status": "triaged", "expected_version": 1},
        headers=auth(private, gaps["user_a"], gaps["org_a"]),
    )
    assert r.status_code == 404


def test_assigning_another_organizations_gap_is_404_not_403(
    client: TestClient, keypair: Any, gaps: dict[str, Any]
) -> None:
    private, _ = keypair
    r = client.post(
        f"/v1/gaps/{gaps['gap_b']}/assign",
        json={"owner_id": str(gaps["mem_a"]), "expected_version": 1},
        headers=auth(private, gaps["user_a"], gaps["org_a"]),
    )
    assert r.status_code == 404


def test_a_gap_cannot_be_assigned_to_another_organizations_member(
    client: TestClient, keypair: Any, gaps: dict[str, Any]
) -> None:
    """The owner id comes from the body, so it is the one field on this route
    that could name another tenant. RLS makes the lookup miss; this asserts the
    route then refuses rather than storing an id that resolves to nobody."""
    private, _ = keypair
    r = client.post(
        f"/v1/gaps/{gaps['gap_a']}/assign",
        json={"owner_id": str(gaps["mem_b"]), "expected_version": 1},
        headers=auth(private, gaps["user_a"], gaps["org_a"]),
    )
    assert r.status_code == 422
    assert "not a member" in r.json()["detail"]


def test_creating_an_action_on_another_organizations_gap_is_404(
    client: TestClient, keypair: Any, gaps: dict[str, Any]
) -> None:
    private, _ = keypair
    r = client.post(
        f"/v1/gaps/{gaps['gap_b']}/actions",
        json={"title": "Recount"},
        headers=auth(private, gaps["user_a"], gaps["org_a"]),
    )
    assert r.status_code == 404


def test_listing_actions_on_another_organizations_gap_is_404(
    client: TestClient, keypair: Any, gaps: dict[str, Any]
) -> None:
    private, _ = keypair
    r = client.get(
        f"/v1/gaps/{gaps['gap_b']}/actions",
        headers=auth(private, gaps["user_a"], gaps["org_a"]),
    )
    assert r.status_code == 404


def test_recording_an_outcome_on_another_organizations_gap_is_404(
    client: TestClient, keypair: Any, gaps: dict[str, Any]
) -> None:
    private, _ = keypair
    r = client.post(
        f"/v1/gaps/{gaps['gap_b']}/outcomes",
        json={
            "measurement_window_start": "2026-08-02T00:00:00Z",
            "measurement_window_end": "2026-08-09T00:00:00Z",
            "metric_definition_id": str(uuid.uuid4()),
            "metric_version": 1,
            "value_before": 1.0,
            "value_after": 1.0,
            "method": "observed",
        },
        headers=auth(private, gaps["user_a"], gaps["org_a"]),
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def test_an_action_can_be_created_and_listed(
    client: TestClient, keypair: Any, gaps: dict[str, Any]
) -> None:
    private, _ = keypair
    headers = auth(private, gaps["user_a"], gaps["org_a"])
    created = client.post(
        f"/v1/gaps/{gaps['gap_a']}/actions",
        json={
            "title": "Recount the affected variants",
            "playbook_id": "retail.stock_truth.recount",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text

    listed = client.get(f"/v1/gaps/{gaps['gap_a']}/actions", headers=headers)
    assert [a["id"] for a in listed.json()] == [created.json()["id"]]


def test_a_terminal_gap_accepts_no_new_actions(
    client: TestClient, keypair: Any, gaps: dict[str, Any], owner_session: Session
) -> None:
    set_status(
        owner_session,
        gaps["gap_a"],
        "dismissed",
        dismissed_at=NOW,
        dismissal_reason_code="duplicate",
        dismissal_note="n",
    )
    private, _ = keypair
    r = client.post(
        f"/v1/gaps/{gaps['gap_a']}/actions",
        json={"title": "Recount"},
        headers=auth(private, gaps["user_a"], gaps["org_a"]),
    )
    assert r.status_code == 422


def test_a_frontline_caller_cannot_create_an_action(
    client: TestClient, keypair: Any, gaps: dict[str, Any], owner_session: Session
) -> None:
    set_role(owner_session, gaps["mem_a"], "frontline")
    private, _ = keypair
    r = client.post(
        f"/v1/gaps/{gaps['gap_a']}/actions",
        json={"title": "Recount"},
        headers=auth(private, gaps["user_a"], gaps["org_a"]),
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def test_every_transition_writes_an_audit_row(
    client: TestClient, keypair: Any, gaps: dict[str, Any], owner_session: Session
) -> None:
    """An audit row that can be absent while the change succeeds is an audit
    trail that proves nothing."""
    private, _ = keypair
    client.post(
        f"/v1/gaps/{gaps['gap_a']}/transition",
        json={
            "to_status": "dismissed",
            "expected_version": 1,
            "reason_code": "duplicate",
            "note": "Already tracked under an earlier gap.",
        },
        headers=auth(private, gaps["user_a"], gaps["org_a"]),
    )

    rows = owner_session.execute(
        text(
            "SELECT action, before, after, reason FROM audit_events "
            "WHERE object_id = :i AND object_type = 'gap'"
        ),
        {"i": str(gaps["gap_a"])},
    ).all()
    assert len(rows) == 1
    action, before, after, reason = rows[0]
    assert action == "gap.dismissed"
    assert before["status"] == "detected"
    assert after["status"] == "dismissed"
    assert reason == "duplicate"


def test_a_refused_transition_writes_no_audit_row(
    client: TestClient, keypair: Any, gaps: dict[str, Any], owner_session: Session
) -> None:
    """Otherwise the audit log records attempts as if they were changes."""
    private, _ = keypair
    client.post(
        f"/v1/gaps/{gaps['gap_a']}/transition",
        json={"to_status": "resolved", "expected_version": 1},
        headers=auth(private, gaps["user_a"], gaps["org_a"]),
    )
    count = owner_session.execute(
        text("SELECT count(*) FROM audit_events WHERE object_id = :i"),
        {"i": str(gaps["gap_a"])},
    ).scalar()
    assert count == 0


def test_the_request_id_reaches_the_audit_row(
    client: TestClient, keypair: Any, gaps: dict[str, Any], owner_session: Session
) -> None:
    private, _ = keypair
    headers = auth(private, gaps["user_a"], gaps["org_a"])
    headers["x-request-id"] = "req-abc-123"
    client.post(
        f"/v1/gaps/{gaps['gap_a']}/assign",
        json={"owner_id": str(gaps["mem_a"]), "expected_version": 1},
        headers=headers,
    )
    request_id = owner_session.execute(
        text("SELECT request_id FROM audit_events WHERE object_id = :i"),
        {"i": str(gaps["gap_a"])},
    ).scalar()
    assert request_id == "req-abc-123"


# ---------------------------------------------------------------------------
# The shared contract
# ---------------------------------------------------------------------------


def test_lifecycle_contract_matches_the_module() -> None:
    """The committed JSON is what the web app reads. If it drifts from the
    module, the UI offers transitions the API refuses — or hides ones it allows.

    This is the same shape as the design tokens: one source, a generated
    artefact, and a test that fails when the artefact goes stale. Without the
    test the artefact is just a second copy with better branding.
    """
    import json
    import sys
    from pathlib import Path

    tools = Path(__file__).resolve().parents[1] / "tools"
    sys.path.insert(0, str(tools))
    from export_gap_lifecycle import CONTRACT_PATH, build

    assert CONTRACT_PATH.exists(), (
        "packages/contracts/src/gap-lifecycle.json is missing. Regenerate with "
        "`uv run python services/api/tools/export_gap_lifecycle.py`."
    )
    committed = json.loads(CONTRACT_PATH.read_text())
    assert committed == build(), (
        "The lifecycle contract has drifted from lifecycle.py. Regenerate with "
        "`uv run python services/api/tools/export_gap_lifecycle.py` and review the diff."
    )


def test_the_contract_is_not_trivially_empty() -> None:
    """A drift test over an empty artefact passes on anything.

    Both halves of the comparison come from the same function, so an export that
    silently produced `{}` would still match a committed `{}`. This asserts the
    contract actually carries the table.
    """
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from export_gap_lifecycle import build

    contract = build()
    assert len(contract["statuses"]) == 7
    assert len(contract["dismissalReasons"]) >= 5
    # Ten legal edges, as test_the_table_enumerates_exactly_the_documented_edges
    # asserts against the module itself.
    assert sum(len(targets) for targets in contract["transitions"].values()) == 10
    assert contract["transitions"]["resolved"] == []
    assert contract["transitionCapability"]["dismissed"] == "gap.dismiss"
