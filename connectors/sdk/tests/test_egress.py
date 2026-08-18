"""The SSRF boundary. Contract test 14, a named release gate.

A connector fetches URLs that came from a tenant's configuration. That makes
every one of these a real attack rather than a hypothetical: a tenant who can
type a URL can point the worker at the cloud metadata service, at a database on
the private network, or at something listening on loopback.

The tests are grouped by the bypass each one closes, because "we block private
IPs" is what everybody believes they have implemented right up until one of
these lands.
"""

from __future__ import annotations

import socket
from typing import Any

import httpx
import pytest
from fitos_connector_sdk.egress import EgressBlockedError, EgressPolicy
from fitos_connector_sdk.http import EgressBoundClient, ResponseTooLargeError


@pytest.fixture
def policy() -> EgressPolicy:
    return EgressPolicy()


def _resolves_to(monkeypatch: pytest.MonkeyPatch, mapping: dict[str, list[str]]) -> None:
    """Pin DNS so the tests are about the policy, not about the internet."""

    def fake_getaddrinfo(host: str, *_a: Any, **_k: Any) -> list[Any]:
        if host not in mapping:
            raise socket.gaierror(f"no fixture for {host}")
        return [
            (
                socket.AF_INET6 if ":" in address else socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (address, 0),
            )
            for address in mapping[host]
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


# ---------------------------------------------------------------------------
# Addresses that must never be reachable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://127.0.0.1/", "loopback"),
        ("http://127.0.0.2/", "loopback"),
        ("http://localhost/", "loopback"),
        ("http://[::1]/", "loopback"),
        ("http://169.254.169.254/latest/meta-data/", "link-local"),
        ("http://[fe80::1]/", "link-local"),
        ("http://10.0.0.5/", "private"),
        ("http://172.16.0.5/", "private"),
        ("http://192.168.1.1/", "private"),
        ("http://[fc00::1]/", "private"),
        ("http://0.0.0.0/", "unspecified"),
        ("http://[::]/", "unspecified"),
        ("http://224.0.0.1/", "multicast"),
        ("http://240.0.0.1/", "reserved"),
    ],
)
def test_a_forbidden_destination_is_refused(
    policy: EgressPolicy, monkeypatch: pytest.MonkeyPatch, url: str, expected: str
) -> None:
    """RELEASE GATE. Each of these is somebody's production incident."""
    _resolves_to(monkeypatch, {"localhost": ["127.0.0.1"]})
    with pytest.raises(EgressBlockedError, match=expected):
        policy.resolve_and_check(url)


def test_the_cloud_metadata_endpoint_is_refused_by_name_too(
    policy: EgressPolicy, monkeypatch: pytest.MonkeyPatch
) -> None:
    """169.254.169.254 has friendly names on several clouds."""
    _resolves_to(monkeypatch, {"metadata.google.internal": ["169.254.169.254"]})
    with pytest.raises(EgressBlockedError, match="link-local"):
        policy.resolve_and_check("http://metadata.google.internal/computeMetadata/v1/")


# ---------------------------------------------------------------------------
# The bypasses
# ---------------------------------------------------------------------------


def test_a_public_hostname_resolving_to_loopback_is_refused(
    policy: EgressPolicy, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Checking the hostname instead of the address is the classic mistake.

    Nothing about `totally-normal.example` looks wrong. It is what it resolves
    to that matters, and an attacker controls that.
    """
    _resolves_to(monkeypatch, {"totally-normal.example": ["127.0.0.1"]})
    with pytest.raises(EgressBlockedError, match="loopback"):
        policy.resolve_and_check("http://totally-normal.example/")


def test_one_bad_address_among_good_ones_refuses_the_whole_host(
    policy: EgressPolicy, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Any-pass is a bypass an attacker can publish on purpose.

    A host with an A record for a public address and another for 127.0.0.1
    defeats a check that stops at the first acceptable answer.
    """
    _resolves_to(monkeypatch, {"mixed.example": ["93.184.216.34", "127.0.0.1"]})
    with pytest.raises(EgressBlockedError, match="loopback"):
        policy.resolve_and_check("http://mixed.example/")


@pytest.mark.parametrize(
    "url",
    [
        "http://[::ffff:127.0.0.1]/",
        "http://[::ffff:169.254.169.254]/",
        "http://[::ffff:10.0.0.1]/",
    ],
)
def test_an_ipv4_mapped_ipv6_address_is_unwrapped_before_judging(
    policy: EgressPolicy, monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    """`::ffff:127.0.0.1` is loopback wearing a v6 costume.

    `IPv6Address('::ffff:127.0.0.1').is_loopback` is False, so a check that
    trusts the v6 flags directly lets the whole v4 private space through.
    """
    _resolves_to(monkeypatch, {})
    with pytest.raises(EgressBlockedError):
        policy.resolve_and_check(url)


@pytest.mark.parametrize(
    "scheme", ["file", "gopher", "ftp", "data", "dict", "jar", "netdoc", "ldap"]
)
def test_only_http_and_https_are_allowed(policy: EgressPolicy, scheme: str) -> None:
    """`file:///etc/passwd` reads the worker's disk; gopher smuggles protocols."""
    with pytest.raises(EgressBlockedError, match="scheme"):
        policy.resolve_and_check(f"{scheme}://example.test/whatever")


def test_a_pivot_port_is_refused(policy: EgressPolicy, monkeypatch: pytest.MonkeyPatch) -> None:
    _resolves_to(monkeypatch, {"public.example": ["93.184.216.34"]})
    with pytest.raises(EgressBlockedError, match="port 5432"):
        policy.resolve_and_check("http://public.example:5432/")


def test_a_public_destination_is_allowed(
    policy: EgressPolicy, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The counterpart. A policy that refuses everything is not a policy."""
    _resolves_to(monkeypatch, {"api.example": ["93.184.216.34"]})
    assert policy.resolve_and_check("https://api.example/v1/orders") == ["93.184.216.34"]


def test_the_allowlist_is_exact_not_a_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    """A suffix rule for `.internal.example` is satisfied by
    `internal.example.attacker.test`, which is a bypass rather than a policy."""
    allowed = EgressPolicy(allow_hosts=frozenset({"warehouse.internal.example"}))
    _resolves_to(
        monkeypatch,
        {
            "warehouse.internal.example": ["10.0.0.9"],
            "warehouse.internal.example.attacker.test": ["10.0.0.9"],
        },
    )

    assert allowed.resolve_and_check("http://warehouse.internal.example/api")
    with pytest.raises(EgressBlockedError, match="private"):
        allowed.resolve_and_check("http://warehouse.internal.example.attacker.test/api")


def test_the_refusal_does_not_disclose_the_internal_address(
    policy: EgressPolicy, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Otherwise the refusal is a network-mapping oracle.

    Told which private address a hostname resolved to, a caller can enumerate
    the internal network one DNS record at a time.
    """
    _resolves_to(monkeypatch, {"probe.example": ["10.11.12.13"]})
    with pytest.raises(EgressBlockedError) as exc:
        policy.resolve_and_check("http://probe.example/")
    assert "10.11.12.13" not in str(exc.value)
    assert "private" in str(exc.value)


# ---------------------------------------------------------------------------
# Redirects — the hop that skips the check
# ---------------------------------------------------------------------------


class _ScriptedTransport(httpx.AsyncBaseTransport):
    """Replays a fixed sequence of responses and records where it was asked to go."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.requested: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requested.append(str(request.url))
        response = self.responses.pop(0)
        return httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            content=response.content,
        )


async def test_a_redirect_to_a_private_address_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RELEASE GATE. The URL that was checked is not the URL that gets fetched.

    A source can answer a perfectly legitimate request with `302 Location:
    http://169.254.169.254/`. A check that ran only on the original URL has
    already passed by then.
    """
    _resolves_to(
        monkeypatch,
        {"api.example": ["93.184.216.34"], "169.254.169.254": ["169.254.169.254"]},
    )
    transport = _ScriptedTransport(
        [
            httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"}),
            httpx.Response(200, content=b"secrets"),
        ]
    )
    client = EgressBoundClient.create(EgressPolicy(), transport=transport)

    with pytest.raises(EgressBlockedError, match="link-local"):
        await client.get("https://api.example/v1/orders")

    assert len(transport.requested) == 1, "the redirect was followed before being checked"
    await client.aclose()


async def test_a_redirect_to_another_public_host_is_followed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The counterpart: legitimate redirects still work."""
    _resolves_to(monkeypatch, {"api.example": ["93.184.216.34"], "cdn.example": ["93.184.216.35"]})
    transport = _ScriptedTransport(
        [
            httpx.Response(302, headers={"location": "https://cdn.example/data.json"}),
            httpx.Response(200, content=b'{"ok":true}'),
        ]
    )
    client = EgressBoundClient.create(EgressPolicy(), transport=transport)

    response = await client.get("https://api.example/v1/orders")
    assert response.status_code == 200
    assert response.content == b'{"ok":true}'
    assert len(transport.requested) == 2
    await client.aclose()


async def test_a_redirect_loop_terminates(monkeypatch: pytest.MonkeyPatch) -> None:
    _resolves_to(monkeypatch, {"api.example": ["93.184.216.34"]})
    transport = _ScriptedTransport(
        [httpx.Response(302, headers={"location": "https://api.example/again"}) for _ in range(20)]
    )
    client = EgressBoundClient.create(EgressPolicy(), transport=transport)

    with pytest.raises(EgressBlockedError, match="redirects"):
        await client.get("https://api.example/start")
    await client.aclose()


# ---------------------------------------------------------------------------
# The client cannot be talked out of the policy
# ---------------------------------------------------------------------------


async def test_the_connection_goes_to_an_address_that_was_checked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Closes the rebind. The check and the connection must agree.

    If the client re-resolved at connect time, a hostname that answered
    `93.184.216.34` during the check could answer `127.0.0.1` a millisecond
    later and the check would have proven nothing.
    """
    _resolves_to(monkeypatch, {"api.example": ["93.184.216.34"]})
    transport = _ScriptedTransport([httpx.Response(200, content=b"ok")])
    client = EgressBoundClient.create(EgressPolicy(), transport=transport)

    await client.get("https://api.example/v1/orders")

    assert transport.requested == ["https://93.184.216.34/v1/orders"], (
        "the request did not go to the checked address"
    )
    await client.aclose()


def test_the_client_exposes_no_unchecked_way_to_make_a_request() -> None:
    """Every public method must go through the policy.

    The client deliberately does not subclass httpx.AsyncClient: inheriting
    would expose `send`, `stream` and `build_request`, each of which is a way
    to make a request that skips the check entirely.
    """
    public = {name for name in dir(EgressBoundClient) if not name.startswith("_")}
    assert public == {"create", "get", "post", "request", "aclose", "max_response_bytes"}


async def test_an_oversized_response_is_abandoned_while_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A source that returns an unbounded body must fail as a refusal.

    Capped while reading, not after: trusting Content-Length is trusting the
    source, and a chunked response does not send one at all.
    """
    _resolves_to(monkeypatch, {"api.example": ["93.184.216.34"]})
    transport = _ScriptedTransport([httpx.Response(200, content=b"x" * 5000)])
    client = EgressBoundClient.create(EgressPolicy(), transport=transport)
    client.max_response_bytes = 1000

    with pytest.raises(ResponseTooLargeError):
        await client.get("https://api.example/big")
    await client.aclose()
