"""Liveness and readiness.

Liveness says the process is up. Readiness says it can serve traffic, and
names which dependency is at fault when it cannot. A readiness probe that
returns 200 while its database is unreachable is worse than no probe: it
turns an outage into a silent one.

Dependency detail is deliberately coarse — a reason code, never a host name,
DSN or credential (docs/threat-model.md T3).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

Probe = Callable[[], Awaitable[bool]]


@dataclass(frozen=True)
class DependencyCheck:
    ok: bool
    detail: str | None = None

    def as_dict(self) -> dict[str, object]:
        body: dict[str, object] = {"ok": self.ok}
        if self.detail is not None:
            body["detail"] = self.detail
        return body


@dataclass
class ReadinessRegistry:
    """Dependencies the API needs before it can serve traffic.

    Phase A registers none — there is nothing to depend on yet. Postgres is
    registered in Phase B, ClickHouse and object storage in Phase C. The
    registry exists now so that adding a dependency cannot forget to add its
    probe.
    """

    probes: dict[str, Probe] = field(default_factory=dict)

    def register(self, name: str, probe: Probe) -> None:
        if name in self.probes:
            raise ValueError(f"duplicate readiness probe: {name}")
        self.probes[name] = probe

    async def evaluate(self) -> tuple[Literal["ready", "degraded"], dict[str, DependencyCheck]]:
        checks: dict[str, DependencyCheck] = {}
        for name, probe in self.probes.items():
            try:
                ok = await probe()
                checks[name] = DependencyCheck(ok=ok, detail=None if ok else "check returned false")
            except Exception as exc:
                checks[name] = DependencyCheck(ok=False, detail=_redact(exc))
        status: Literal["ready", "degraded"] = (
            "ready" if all(c.ok for c in checks.values()) else "degraded"
        )
        return status, checks


def _redact(exc: Exception) -> str:
    """Exception type only. The message may carry a DSN or a credential."""
    return type(exc).__name__
