"""Cross-tenant isolation, proven against a real PostgreSQL.

Every test here uses the application role, which is NOBYPASSRLS. That is the
point: these assertions are about what the *database* refuses, not about what
the service layer remembers to filter.

The release gate is `test_rls_alone_blocks_the_query`. It issues a query with no
organization filter at all — the exact bug a tired reviewer misses — and proves
the row is still invisible.
"""

from __future__ import annotations

import uuid

import pytest
from conftest import requires_db
from fitos_api.db import current_organization, organization_scope
from fitos_api.models import AuditEvent, Membership
from fitos_api.tenancy_sql import ORG_SCOPED_TABLES
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

pytestmark = requires_db


def test_scope_binds_the_transaction_to_one_organization(
    app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
) -> None:
    org_a, _ = two_orgs
    with organization_scope(app_session, org_a):
        assert current_organization(app_session) == org_a


def test_scope_does_not_survive_the_transaction(
    app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """SET LOCAL, not SET.

    A pooled connection must not carry one request's tenant into the next.
    """
    org_a, _ = two_orgs
    with organization_scope(app_session, org_a):
        assert current_organization(app_session) == org_a
    app_session.rollback()
    assert current_organization(app_session) is None


def test_rls_alone_blocks_the_query(
    app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """RELEASE GATE — defence in depth is real, not assumed.

    The query below has no WHERE organization_id clause. If the service layer
    forgot its filter, this is what production would run. The database must
    still return nothing from the other organization.
    """
    org_a, org_b = two_orgs

    with organization_scope(app_session, org_a):
        rows = app_session.execute(text("SELECT organization_id FROM memberships")).scalars().all()

    assert rows, "expected org A's own membership to be visible"
    assert set(rows) == {org_a}, (
        "a membership from another organization was visible without a filter"
    )
    assert org_b not in rows


def test_a_caller_cannot_read_another_organizations_membership(
    app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
) -> None:
    org_a, org_b = two_orgs
    with organization_scope(app_session, org_a):
        found = (
            app_session.query(Membership).filter(Membership.organization_id == org_b).one_or_none()
        )
    assert found is None


def test_a_caller_cannot_write_into_another_organization(
    app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID], owner_session: Session
) -> None:
    """WITH CHECK, not just USING.

    Reading another tenant is disclosure; writing into one is worse, and a
    USING-only policy permits it.
    """
    org_a, org_b = two_orgs
    from fitos_api.models import User

    user = User(email=f"x-{uuid.uuid4().hex[:8]}@example.test")
    owner_session.add(user)
    owner_session.commit()

    with organization_scope(app_session, org_a):
        app_session.add(Membership(organization_id=org_b, user_id=user.id, role="frontline"))
        with pytest.raises(ProgrammingError) as exc:
            app_session.flush()

    assert "row-level security" in str(exc.value).lower()


def test_no_organization_context_means_no_rows(
    app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """An unscoped transaction is not a permissive one.

    `current_setting(..., true)` returns NULL when unset, and `= NULL` is never
    true, so the policy denies rather than defaults open.
    """
    rows = app_session.execute(text("SELECT organization_id FROM memberships")).scalars().all()
    assert rows == []


def test_the_organization_row_itself_is_scoped(
    app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
) -> None:
    org_a, org_b = two_orgs
    with organization_scope(app_session, org_a):
        visible = app_session.execute(text("SELECT id FROM organizations")).scalars().all()
    assert set(visible) == {org_a}
    assert org_b not in visible


def test_every_org_scoped_table_has_rls_enabled_and_forced(app_session: Session) -> None:
    """Catches the table that ships without a policy.

    FORCE matters as much as ENABLE: without it the table owner is exempt, and
    'the owner is exempt' is how a migration script quietly reads everything.
    """
    rows = app_session.execute(
        text(
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname = ANY(:names)"
        ),
        {"names": [*ORG_SCOPED_TABLES, "organizations"]},
    ).all()

    seen = {r[0]: (r[1], r[2]) for r in rows}
    for table in (*ORG_SCOPED_TABLES, "organizations"):
        assert table in seen, f"{table} not found"
        enabled, forced = seen[table]
        assert enabled, f"{table} does not have RLS enabled"
        assert forced, f"{table} does not FORCE RLS, so its owner is exempt"


def test_the_application_role_cannot_bypass_rls(app_session: Session) -> None:
    can_bypass = app_session.execute(
        text("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user")
    ).scalar()
    assert can_bypass is False, (
        "the application role can bypass RLS, which voids every policy above"
    )


class TestAuditIsAppendOnly:
    """docs/threat-model.md T13 — repudiation.

    Append-only is enforced by the absence of a grant, so it holds for any code
    path, including one that has not been written yet.
    """

    def _insert(self, session: Session, org: uuid.UUID) -> None:
        session.add(
            AuditEvent(
                organization_id=org,
                action="membership.created",
                object_type="membership",
                object_id=str(uuid.uuid4()),
                after={"role": "manager"},
            )
        )
        session.flush()

    def test_insert_is_permitted(
        self, app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        org_a, _ = two_orgs
        with organization_scope(app_session, org_a):
            self._insert(app_session, org_a)
            count = app_session.execute(text("SELECT count(*) FROM audit_events")).scalar()
        assert count == 1

    def test_update_is_refused_by_the_database(
        self, app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        org_a, _ = two_orgs
        with organization_scope(app_session, org_a):
            self._insert(app_session, org_a)
            with pytest.raises(ProgrammingError) as exc:
                app_session.execute(text("UPDATE audit_events SET action = 'tampered'"))
        assert "permission denied" in str(exc.value).lower()

    def test_delete_is_refused_by_the_database(
        self, app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        org_a, _ = two_orgs
        with organization_scope(app_session, org_a):
            self._insert(app_session, org_a)
            with pytest.raises(ProgrammingError) as exc:
                app_session.execute(text("DELETE FROM audit_events"))
        assert "permission denied" in str(exc.value).lower()

    def test_audit_rows_are_tenant_scoped(
        self, app_session: Session, two_orgs: tuple[uuid.UUID, uuid.UUID]
    ) -> None:
        org_a, org_b = two_orgs
        with organization_scope(app_session, org_a):
            self._insert(app_session, org_a)
            app_session.commit()

        with organization_scope(app_session, org_b):
            rows = (
                app_session.execute(text("SELECT organization_id FROM audit_events"))
                .scalars()
                .all()
            )
        assert rows == [], "org B could read org A's audit trail"
