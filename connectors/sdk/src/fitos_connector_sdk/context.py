"""What a connector is handed, and what it is denied.

`ConnectorContext` is the whole enforcement mechanism. A connector receives one
and cannot construct the things on it: not the HTTP client (which carries the
egress policy), not the secrets (which arrive through a resolver that records
what was read), not the rate limiter. Anything a connector could build for
itself is a control it could forget.

The secret resolver deserves particular care, because contract test 13 says a
secret must never appear in a log, an error, a trace or the run record — and
the usual way that promise breaks is not a `print`, it is an exception
`repr()` that happens to include a config dict.

So secrets never enter the config dict at all. `config` holds settings;
`secrets.get("access_token")` returns the value and nothing keeps a reference
to it. `SecretStr`-style wrapping is not enough on its own — the wrapper stops
an accidental `str()`, but a caller who genuinely needs the plaintext still
gets it, and from there it can be logged. What actually helps is that the
plaintext has one narrow path and a short life.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from fitos_connector_sdk.egress import EgressPolicy
from fitos_connector_sdk.http import EgressBoundClient
from fitos_connector_sdk.types import RateLimitKind, RateLimitModel


class MissingSecretError(KeyError):
    """A required secret was not configured.

    The message names the key, never the value of anything nearby.
    """


class SecretResolver:
    """Reads secrets, and remembers only which keys were asked for.

    The `accessed` set exists so a run record can say "this run used
    access_token" without the run record ever holding one. That is the
    difference between an audit trail and a leak.
    """

    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = dict(values)
        self.accessed: set[str] = set()

    def get(self, key: str) -> str:
        if key not in self._values:
            raise MissingSecretError(f"secret {key!r} is not configured for this connection")
        self.accessed.add(key)
        return self._values[key]

    def has(self, key: str) -> bool:
        return key in self._values

    def redact(self, text: str) -> str:
        """Replace any configured secret found in a string.

        The last line of defence, for text assembled by a third-party library
        that has no idea it is holding a token — an httpx error quoting a URL
        with a key in the query string, for instance. It is not a substitute for
        not putting secrets in strings; it is what catches the case where
        somebody else did.
        """
        cleaned = text
        for key, value in self._values.items():
            if value and value in cleaned:
                cleaned = cleaned.replace(value, f"[redacted:{key}]")
        return cleaned

    def __repr__(self) -> str:
        # Never the values. A resolver that renders its contents ends up in a
        # traceback the first time something raises while holding one.
        return f"SecretResolver(keys={sorted(self._values)!r})"


@dataclass
class RateLimiter:
    """A leaky bucket, and the thing that makes contract test 11 pass.

    A 429 is a backoff instruction, not a failure. A connector that treats it as
    an error turns a busy source into a broken connection, and the run summary
    then blames the source for the client's impatience.
    """

    model: RateLimitModel
    _tokens: float = field(init=False)
    _last: float = field(init=False)
    waits: int = field(default=0, init=False)
    waited_seconds: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        self._tokens = float(self.model.capacity)
        self._last = time.monotonic()

    async def acquire(self, cost: float = 1.0) -> None:
        if self.model.kind is RateLimitKind.NONE:
            return
        while True:
            now = time.monotonic()
            self._tokens = min(
                float(self.model.capacity),
                self._tokens + (now - self._last) * self.model.restore_per_second,
            )
            self._last = now
            if self._tokens >= cost:
                self._tokens -= cost
                return
            deficit = cost - self._tokens
            delay = deficit / self.model.restore_per_second
            self.waits += 1
            self.waited_seconds += delay
            await asyncio.sleep(delay)


@dataclass
class ProgressReporter:
    """Counts that end up in the run record.

    `quarantined` is here rather than derived, because a rejected record must be
    counted even when nothing downstream ever asks. Silent rejection is
    prohibited: a run that read 10,000 records and wrote 9,300 has to say so.
    """

    records_read: int = 0
    records_written: int = 0
    records_quarantined: int = 0
    batches: int = 0

    def read(self, count: int) -> None:
        self.records_read += count

    def wrote(self, count: int) -> None:
        self.records_written += count

    def quarantined(self, count: int) -> None:
        self.records_quarantined += count

    def batch(self) -> None:
        self.batches += 1


@dataclass
class ConnectorContext:
    """Everything a connector may use, and nothing it may construct.

    `organization_id` comes from the run, which got it from a verified token.
    It is never read from connector config: a connector that could name its own
    tenant would be a cross-tenant write waiting for a typo.
    """

    organization_id: UUID
    connection_id: UUID
    config: Mapping[str, Any]
    secrets: SecretResolver
    http: EgressBoundClient
    rate_limiter: RateLimiter
    progress: ProgressReporter
    trace_id: str = ""
    fixture_mode: bool = False

    @classmethod
    def create(
        cls,
        *,
        organization_id: UUID,
        connection_id: UUID,
        config: Mapping[str, Any] | None = None,
        secrets: Mapping[str, str] | None = None,
        rate_limit: RateLimitModel | None = None,
        egress: EgressPolicy | None = None,
        transport: Any = None,
        trace_id: str = "",
        fixture_mode: bool = False,
    ) -> ConnectorContext:
        resolver = SecretResolver(secrets or {})
        policy = egress or EgressPolicy()
        return cls(
            organization_id=organization_id,
            connection_id=connection_id,
            config=dict(config or {}),
            secrets=resolver,
            http=EgressBoundClient.create(policy, transport=transport),
            rate_limiter=RateLimiter(
                rate_limit or RateLimitModel(kind=RateLimitKind.NONE, capacity=1)
            ),
            progress=ProgressReporter(),
            trace_id=trace_id,
            fixture_mode=fixture_mode,
        )

    async def aclose(self) -> None:
        await self.http.aclose()
