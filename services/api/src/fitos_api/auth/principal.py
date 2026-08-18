"""The verified caller.

`organization_id` on a Principal has exactly one origin: a verified token
claim. It is never read from a request body, query string, header or cookie.
The type exists so that "where did this org id come from" has one answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fitos_api.capabilities import Capability, Role, capabilities_for


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    organization_id: UUID
    membership_id: UUID
    role: Role
    granted: frozenset[Capability] = frozenset()

    @property
    def capabilities(self) -> frozenset[Capability]:
        return capabilities_for(self.role, granted=self.granted or None)

    def can(self, capability: Capability) -> bool:
        return capability in self.capabilities
