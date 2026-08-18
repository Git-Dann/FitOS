"""Invitation codes.

The code is a bearer credential. Three properties are what make it safe to send
by email:

- **It is never stored.** Only `sha256(secret)` reaches the database, so the
  table is worthless to anyone who reads it. The plaintext exists in one
  response body and then only in the recipient's inbox.
- **It is looked up by hash, not compared.** The lookup is an indexed equality
  on a digest, so there is no secret-dependent comparison to time.
- **It carries its own organization.** The code is `<organization_id>.<secret>`,
  which lets the API open the tenant scope before searching. Redemption
  therefore happens inside RLS rather than needing an exemption to find the row.
  The organization half is routing, not authority: naming an organization gets
  you nothing without the secret, and the secret is only ever found within the
  organization it was issued for.

`secrets.token_urlsafe(32)` is 256 bits of entropy from the OS CSPRNG. The
expiry is short by default because an invitation is an offer, not a standing
grant.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

DEFAULT_TTL = timedelta(days=7)
SECRET_BYTES = 32


class InvalidCodeError(Exception):
    """The code is not well-formed. Never says which half was wrong."""


@dataclass(frozen=True)
class IssuedCode:
    """A freshly minted code: the plaintext to send, and the hash to store."""

    code: str
    code_hash: str


def issue(organization_id: uuid.UUID) -> IssuedCode:
    secret = secrets.token_urlsafe(SECRET_BYTES)
    return IssuedCode(code=f"{organization_id}.{secret}", code_hash=hash_secret(secret))


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def parse(code: str) -> tuple[uuid.UUID, str]:
    """Split a code into the organization it addresses and the hash to look up.

    Returns the *hash* of the secret rather than the secret, so a caller cannot
    accidentally log or store the plaintext half after parsing.
    """
    organization_part, separator, secret = code.partition(".")
    if not separator or not secret:
        raise InvalidCodeError("malformed invitation code")
    try:
        organization_id = uuid.UUID(organization_part)
    except ValueError as exc:
        raise InvalidCodeError("malformed invitation code") from exc
    return organization_id, hash_secret(secret)


def default_expiry(now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) + DEFAULT_TTL
