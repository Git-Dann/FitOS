"""Database access and the tenant boundary.

Two things here are load-bearing:

1. `organization_scope` sets `app.current_organization_id` with SET LOCAL, so
   the setting is scoped to the transaction and cannot leak into the next
   checkout of a pooled connection.
2. The application connects as a role that cannot bypass RLS. If the service
   layer forgets a filter, the database still refuses — which is the property
   the cross-tenant tests actually assert (docs/threat-model.md T1).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# Set by the application at startup; tests build their own.
_engine: Engine | None = None


def configure(database_url: str, **kwargs: Any) -> Engine:
    global _engine
    _engine = create_engine(database_url, pool_pre_ping=True, **kwargs)
    return _engine


def engine() -> Engine:
    if _engine is None:
        raise RuntimeError("database engine not configured; call configure() at startup")
    return _engine


def session_factory(bind: Engine | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=bind or engine(), expire_on_commit=False)


@contextmanager
def organization_scope(session: Session, organization_id: UUID) -> Iterator[Session]:
    """Bind a transaction to one organization.

    SET LOCAL, not SET: the value dies with the transaction. A connection
    returned to the pool carries no tenant context, so the next request cannot
    inherit the previous request's organization.

    The parameter is bound, never interpolated — this string reaches the
    database as SQL and an f-string here would be an injection point.
    """
    if not session.in_transaction():
        session.begin()
    session.execute(
        text("SELECT set_config('app.current_organization_id', :org, true)"),
        {"org": str(organization_id)},
    )
    try:
        yield session
    finally:
        # The caller commits or rolls back; either ends the transaction and
        # therefore the setting.
        pass


def current_organization(session: Session) -> UUID | None:
    """The organization the current transaction is bound to, if any."""
    raw = session.execute(
        text("SELECT current_setting('app.current_organization_id', true)")
    ).scalar()
    return UUID(raw) if raw else None
