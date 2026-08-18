"""Capabilities, not roles.

`can("gap.assign")`, never `role == "manager"`. The distinction matters for two
reasons that only show up later:

  1. A new identity provider supplies different role claims. If product code
     compares role names, every comparison is a migration. If it asks for a
     capability, the role-to-capability map absorbs the difference — which is
     what makes the auth-provider boundary in ADR 0005 cheap.
  2. An organization can be granted an exception (see `gap.view_exposure`)
     without inventing a new role.

A lint rule fails the build on a role-name comparison in application code.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    FRONTLINE = "frontline"
    MANAGER = "manager"
    ANALYST = "analyst"
    ADMIN = "admin"
    OWNER = "owner"
    PRESENTER_DEMO = "presenter-demo"


class Capability(StrEnum):
    # Gaps
    GAP_VIEW = "gap.view"
    GAP_ASSIGN = "gap.assign"
    GAP_TRANSITION = "gap.transition"
    GAP_DISMISS = "gap.dismiss"
    GAP_COMMENT = "gap.comment"
    # Modelled money. Withheld from frontline by default — see below.
    GAP_VIEW_EXPOSURE = "gap.view_exposure"
    # Metrics and sources
    METRIC_VIEW = "metric.view"
    METRIC_QUERY = "metric.query"
    METRIC_VIEW_QUERY_DETAIL = "metric.view_query_detail"
    SOURCE_VIEW = "source.view"
    SOURCE_MANAGE = "source.manage"
    # Administration
    MAPPING_MANAGE = "mapping.manage"
    MEMBER_MANAGE = "member.manage"
    AUDIT_VIEW = "audit.view"
    RETENTION_MANAGE = "retention.manage"
    DEMO_CONTROL = "demo.control"
    ORG_MANAGE = "org.manage"


_FRONTLINE: frozenset[Capability] = frozenset(
    {
        Capability.GAP_VIEW,
        Capability.GAP_COMMENT,
    }
)

_MANAGER: frozenset[Capability] = _FRONTLINE | {
    Capability.GAP_ASSIGN,
    Capability.GAP_TRANSITION,
    Capability.GAP_DISMISS,
    Capability.GAP_VIEW_EXPOSURE,
    Capability.METRIC_VIEW,
    Capability.METRIC_QUERY,
    Capability.SOURCE_VIEW,
}

_ANALYST: frozenset[Capability] = _MANAGER | {
    Capability.METRIC_VIEW_QUERY_DETAIL,
}

_ADMIN: frozenset[Capability] = _ANALYST | {
    Capability.SOURCE_MANAGE,
    Capability.MAPPING_MANAGE,
    Capability.MEMBER_MANAGE,
    Capability.AUDIT_VIEW,
    Capability.RETENTION_MANAGE,
    Capability.DEMO_CONTROL,
}

_OWNER: frozenset[Capability] = _ADMIN | {Capability.ORG_MANAGE}

# The presenter runs a scripted story across roles on demo tenants only. It can
# see exposure because the story is about exposure, but it cannot change
# anything: a demo must not be able to mutate a gap ledger.
_PRESENTER_DEMO: frozenset[Capability] = frozenset(
    {
        Capability.GAP_VIEW,
        Capability.GAP_VIEW_EXPOSURE,
        Capability.METRIC_VIEW,
        Capability.METRIC_QUERY,
        Capability.SOURCE_VIEW,
    }
)

ROLE_CAPABILITIES: dict[Role, frozenset[Capability]] = {
    Role.FRONTLINE: _FRONTLINE,
    Role.MANAGER: _MANAGER,
    Role.ANALYST: _ANALYST,
    Role.ADMIN: _ADMIN,
    Role.OWNER: _OWNER,
    Role.PRESENTER_DEMO: _PRESENTER_DEMO,
}


def capabilities_for(
    role: Role, *, granted: frozenset[Capability] | None = None
) -> frozenset[Capability]:
    """Capabilities for a role, plus any per-organization grants.

    `granted` exists for the exception the brief allows: frontline sees no
    modelled money by default, "unless the role has permission and a direct
    need". That exception is a capability grant on the membership, not a code
    change and not a UI condition.
    """
    base = ROLE_CAPABILITIES[role]
    return base | granted if granted else base
