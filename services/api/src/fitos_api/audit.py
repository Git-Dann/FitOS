"""Audit writing.

Every state transition writes one of these. The table grants the application
role INSERT and SELECT only, so a caller cannot rewrite history even if a code
path tried (docs/threat-model.md T13).

`before` and `after` are whole-field snapshots of what changed, not a diff:
reconstructing a diff months later requires knowing the schema at the time,
and a snapshot does not.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from fitos_api.auth.principal import Principal
from fitos_api.models import AuditEvent


def record(
    session: Session,
    *,
    principal: Principal,
    action: str,
    object_type: str,
    object_id: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        organization_id=principal.organization_id,
        actor_membership_id=principal.membership_id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        before=before,
        after=after,
        reason=reason,
        request_id=request_id,
        trace_id=trace_id,
    )
    session.add(event)
    session.flush()
    return event
