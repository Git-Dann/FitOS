"""Where a connector is allowed to send a request.

This is the SSRF boundary. A connector fetches URLs that came from a tenant's
configuration, which means a tenant can point one at anything the worker can
reach — the cloud metadata endpoint, a database on the private network, a
service listening on loopback. The classic outcome is credential theft from
`169.254.169.254`, and it needs no exotic bug: it needs a URL field and an HTTP
client that does what it is told.

Four rules, and the order matters:

1. **Scheme allowlist.** Only http and https. `file://` reads the worker's disk,
   `gopher://` and `ftp://` are protocol-smuggling primitives.
2. **Resolve, then judge the address.** Judging the hostname is not enough:
   `evil.test` can resolve to `127.0.0.1`, and it can resolve differently the
   second time you ask. So the check runs against resolved addresses and the
   *connection uses one of the addresses that was checked* — otherwise the DNS
   answer can change between the check and the connect (a TOCTOU rebind) and the
   check proves nothing.
3. **Every address must pass.** A hostname with one public and one private
   address is refused. Accepting it would let an attacker publish exactly that.
4. **Redirects are re-checked.** A public URL that 302s to `http://127.0.0.1`
   defeats a check that only ran on the original. Every hop is a fresh decision.

What counts as forbidden is deliberately broader than "private": loopback,
link-local (which is where cloud metadata lives), unique-local, multicast,
reserved and unspecified ranges are all refused, for IPv4 and IPv6 alike,
including IPv4-mapped IPv6 forms like `::ffff:127.0.0.1` that read as public to
a naive check.

The allowlist exists for tests and for the one legitimate case of a
self-hosted source on a private network, which is a deliberate per-connection
setting and not a default.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import urlsplit

ALLOWED_SCHEMES = frozenset({"http", "https"})

# Ports that are never a legitimate HTTP source and are common pivot targets.
# This is defence in depth: the address check above is the real control.
BLOCKED_PORTS = frozenset({22, 23, 25, 445, 3306, 5432, 6379, 9000, 11211, 27017})


class EgressBlockedError(Exception):
    """The request was refused before it left the process.

    The message names the reason and the host, never a resolved internal
    address — telling a caller *which* private address their hostname resolved
    to turns a refusal into a network-mapping oracle.
    """


def _is_forbidden(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    """Return the reason this address is refused, or None if it is acceptable."""
    # An IPv4-mapped IPv6 address (::ffff:127.0.0.1) is the same host as its
    # IPv4 form, but `is_loopback` on the v6 object is False. Unwrap first.
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return _is_forbidden(address.ipv4_mapped)
        # 6to4 and Teredo embed a v4 address the same way.
        if address.sixtofour is not None:
            return _is_forbidden(address.sixtofour)
        if address.teredo is not None:
            return _is_forbidden(address.teredo[1])

    # Most specific first. `is_private` is true for the unspecified address and
    # for the reserved 240/4 block as well, so testing it early would report
    # every one of these as merely "private" — still refused, but a worse
    # answer for whoever has to work out why their URL was rejected.
    if address.is_loopback:
        return "loopback address"
    if address.is_link_local:
        # 169.254.169.254 lives here. This is the cloud metadata service.
        return "link-local address"
    if address.is_unspecified:
        return "unspecified address"
    if address.is_multicast:
        return "multicast address"
    if address.is_reserved:
        return "reserved address"
    if address.is_private:
        return "private address"
    return None


@dataclass(frozen=True)
class EgressPolicy:
    """What this connection may reach.

    `allow_hosts` is an escape hatch for a self-hosted source on a private
    network and for tests. It is exact-match on the hostname, never a suffix
    match: a suffix rule for `.internal.example` is satisfied by
    `evil.internal.example.attacker.test`, which is a bypass rather than a
    policy.
    """

    allow_hosts: frozenset[str] = field(default_factory=frozenset)
    allow_ports: frozenset[int] = field(default_factory=frozenset)

    def resolve_and_check(self, url: str) -> list[str]:
        """Refuse the URL, or return the addresses it is allowed to connect to.

        The returned addresses are the ones that were checked. Connecting to
        anything else — including whatever DNS says a moment later — reopens
        the rebinding hole this closes.
        """
        parts = urlsplit(url)

        if parts.scheme not in ALLOWED_SCHEMES:
            raise EgressBlockedError(
                f"scheme {parts.scheme!r} is not allowed; connectors may use http or https only"
            )

        host = parts.hostname
        if not host:
            raise EgressBlockedError("the URL has no host")

        port = parts.port or (443 if parts.scheme == "https" else 80)
        if port in BLOCKED_PORTS and port not in self.allow_ports:
            raise EgressBlockedError(f"port {port} is not an allowed destination")

        if host in self.allow_hosts:
            return _resolve(host)

        addresses = _resolve(host)
        for raw in addresses:
            reason = _is_forbidden(ipaddress.ip_address(raw))
            if reason is not None:
                # The reason is named; the address is not. Echoing it would let
                # a caller map the internal network one hostname at a time.
                raise EgressBlockedError(
                    f"{host} resolves to a {reason}, which connectors may not reach"
                )

        return addresses


def _resolve(host: str) -> list[str]:
    """Every address for a host, v4 and v6.

    An address literal is returned as-is rather than sent to the resolver.
    Resolving it would be a needless round trip, and more importantly the
    caller must not be able to make the policy depend on DNS for a destination
    that never needed it.
    """
    try:
        return [str(ipaddress.ip_address(host))]
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise EgressBlockedError(f"{host} could not be resolved") from exc

    addresses: list[str] = []
    for info in infos:
        address = str(info[4][0])
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise EgressBlockedError(f"{host} resolved to no addresses")
    return addresses
