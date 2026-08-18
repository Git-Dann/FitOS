"""Signed webhook verification, and the two things that go wrong with it.

**The signature.** Computed over the exact bytes received, compared in constant
time. Both halves matter and both are commonly got wrong:

- Signing a re-serialised body instead of the raw bytes fails the moment a
  source emits keys in a different order or spells a float differently, and
  worse, it can *succeed* on a payload whose meaning changed during the
  round trip. `raw` here is always the bytes off the wire.
- `==` on a digest leaks the position of the first differing byte through
  timing. `hmac.compare_digest` does not. This matters less over the internet
  than the textbooks suggest and costs nothing to get right.

**The replay.** A valid signature says the payload came from the source; it says
nothing about whether it has already been delivered. Sources retry, proxies
duplicate, and an attacker who captures one signed delivery can send it again
forever. Two defences, because neither alone is enough:

- A **timestamp** in the signed material, rejected outside a tolerance window.
  Without it a captured delivery is valid indefinitely. The timestamp must be
  inside the signature, or an attacker simply edits it.
- A **delivery id** recorded once. The window still admits replays inside it,
  and duplicate deliveries from the source are legitimate but must not create a
  second fact. This is contract test 8, a release gate: the same signed payload
  twice yields one canonical fact.

The dedupe store is an interface with an in-memory implementation for tests and
a database-backed one for the runner. It is keyed by (organization, connector,
delivery id) so two tenants cannot collide, and so a replay across tenants is
not silently accepted as a first delivery.
"""

from __future__ import annotations

import hashlib
import hmac
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fitos_connector_sdk.types import WebhookVerification

# How far out of date a signed timestamp may be. Five minutes is the usual
# choice: long enough for clock drift and a slow retry, short enough that a
# captured delivery stops being useful quickly.
DEFAULT_TOLERANCE = timedelta(minutes=5)


class DeliveryStore(ABC):
    """Remembers which deliveries have been seen.

    `record_if_new` is one atomic operation on purpose. Checking and then
    inserting is a race: two workers handling the same retry both see "not
    seen", both insert, and the duplicate the whole mechanism exists to prevent
    happens anyway. The database implementation relies on a unique constraint
    for exactly this reason.
    """

    @abstractmethod
    def record_if_new(self, *, organization_id: UUID, connector_key: str, delivery_id: str) -> bool:
        """Return True if this delivery is new, False if it has been seen."""


@dataclass
class InMemoryDeliveryStore(DeliveryStore):
    """For tests and for a single-process fixture run."""

    seen: set[tuple[UUID, str, str]] = field(default_factory=set)

    def record_if_new(self, *, organization_id: UUID, connector_key: str, delivery_id: str) -> bool:
        key = (organization_id, connector_key, delivery_id)
        if key in self.seen:
            return False
        self.seen.add(key)
        return True


def signed_payload(timestamp: str, raw: bytes) -> bytes:
    """What actually gets signed: the timestamp and the body, bound together.

    Signing the body alone leaves the timestamp editable, which removes the
    entire point of having one.
    """
    return timestamp.encode() + b"." + raw


def compute_signature(secret: str, timestamp: str, raw: bytes) -> str:
    return hmac.new(secret.encode(), signed_payload(timestamp, raw), hashlib.sha256).hexdigest()


def verify_signature(
    *,
    secret: str,
    raw: bytes,
    signature: str,
    timestamp: str,
    tolerance: timedelta = DEFAULT_TOLERANCE,
    now: datetime | None = None,
) -> WebhookVerification:
    """Check the signature and the freshness. Fails closed on anything unexpected.

    The reason strings are deliberately coarse. Distinguishing "bad signature"
    from "signature for a different body" would tell an attacker which half of
    their forgery to work on.
    """
    try:
        sent_at = datetime.fromtimestamp(int(timestamp), tz=UTC)
    except (ValueError, OverflowError, OSError):
        return WebhookVerification(ok=False, reason="timestamp is not a unix time")

    current = now or datetime.now(UTC)
    age = abs(current - sent_at)
    if age > tolerance:
        # Both directions. A far-future timestamp is as suspicious as an old
        # one and would otherwise extend the replay window indefinitely.
        return WebhookVerification(ok=False, reason="timestamp outside tolerance")

    expected = compute_signature(secret, timestamp, raw)
    if not hmac.compare_digest(expected, signature):
        return WebhookVerification(ok=False, reason="signature mismatch")

    return WebhookVerification(ok=True)


def accept_delivery(
    *,
    store: DeliveryStore,
    organization_id: UUID,
    connector_key: str,
    delivery_id: str,
) -> bool:
    """Record the delivery. False means it is a duplicate and must not be processed again.

    A duplicate is not an error — sources retry deliberately, and a retry after
    a timeout is correct behaviour on their part. It returns 200 and does
    nothing, which is what stops a retry storm.
    """
    return store.record_if_new(
        organization_id=organization_id, connector_key=connector_key, delivery_id=delivery_id
    )


def header(headers: Mapping[str, str], name: str) -> str | None:
    """Case-insensitive header lookup.

    HTTP header names are case-insensitive and different proxies normalise them
    differently. A verifier that reads `X-Signature` and misses `x-signature`
    fails closed, which is safe but presents as an outage.
    """
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return None
