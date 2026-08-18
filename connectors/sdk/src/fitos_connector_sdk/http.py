"""The only HTTP client a connector gets.

A connector cannot construct its own client. That is the whole design: an
egress policy a connector has to remember to apply is an egress policy that
gets forgotten, and the forgetting looks exactly like working code. So the
client arrives on `ConnectorContext` with the policy already fastened to it.

Three properties are worth stating because they are easy to lose:

**The connection goes to an address that was checked.** `resolve_and_check`
returns the addresses it validated, and the request is made against one of
them with the original hostname preserved in the Host header and in TLS SNI.
Re-resolving at connect time would let the DNS answer change between the check
and the connection — a rebind — and the check would prove nothing about where
the bytes actually went.

**Redirects are followed by hand.** httpx's own redirect following would skip
the policy on every hop after the first, so a public URL that 302s to
`http://169.254.169.254` would sail through. `follow_redirects=False` plus an
explicit loop means each hop is checked like a fresh request.

**The surface is deliberately small.** The request parameters are named rather
than `**kwargs`, so there is no way to reach through to httpx and hand it
something the policy never saw.

Responses are size-capped while streaming rather than after. A source that
returns an unbounded body should fail as a refusal, not as the worker's memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import SplitResult, urljoin, urlsplit, urlunsplit

import httpx

from fitos_connector_sdk.egress import EgressBlockedError, EgressPolicy

DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)
MAX_REDIRECTS = 5
MAX_RESPONSE_BYTES = 64 * 1024 * 1024

REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class ResponseTooLargeError(Exception):
    """The source sent more than the connector is willing to hold."""


@dataclass
class EgressBoundClient:
    """An httpx client with the egress policy applied to every request.

    Not a subclass of httpx.AsyncClient on purpose. Inheriting would expose
    `stream`, `send` and `build_request`, each of which is another way to make
    a request that skips the check. A connector holding this object can only do
    what this class allows.
    """

    policy: EgressPolicy
    _client: httpx.AsyncClient
    max_response_bytes: int = MAX_RESPONSE_BYTES

    @classmethod
    def create(
        cls,
        policy: EgressPolicy,
        *,
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> EgressBoundClient:
        client = httpx.AsyncClient(
            headers=headers or {},
            timeout=timeout or DEFAULT_TIMEOUT,
            follow_redirects=False,
            transport=transport,
        )
        return cls(policy=policy, _client=client)

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        return await self.request("GET", url, headers=headers, params=params)

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        json: Any = None,
        content: bytes | None = None,
    ) -> httpx.Response:
        return await self.request(
            "POST", url, headers=headers, params=params, json=json, content=content
        )

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        json: Any = None,
        content: bytes | None = None,
    ) -> httpx.Response:
        """Make a request, checking the policy on the URL and on every redirect."""
        current = url
        for _hop in range(MAX_REDIRECTS + 1):
            response = await self._checked_request(
                method, current, headers=headers, params=params, json=json, content=content
            )
            if response.status_code not in REDIRECT_STATUSES:
                return response

            location = response.headers.get("location")
            if not location:
                return response

            current = urljoin(current, location)
            # A 303, or a 301/302 on a non-HEAD request, becomes a GET by
            # convention. The body goes with it, which also stops a payload
            # being replayed to a host that was never its intended recipient.
            if response.status_code in (301, 302, 303) and method.upper() != "HEAD":
                method = "GET"
                json = None
                content = None

        raise EgressBlockedError(f"more than {MAX_REDIRECTS} redirects; refusing to follow further")

    async def _checked_request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None,
        params: dict[str, str] | None,
        json: Any,
        content: bytes | None,
    ) -> httpx.Response:
        # Raises EgressBlockedError before a socket is opened.
        addresses = self.policy.resolve_and_check(url)

        parts = urlsplit(url)
        host = parts.hostname
        if host is None:  # pragma: no cover - resolve_and_check already refused
            raise EgressBlockedError("the URL has no host")

        # Connect to a checked address, but keep the hostname for Host and SNI.
        # Without the pin, httpx would resolve again and could get a different
        # answer; without the hostname, TLS verification and virtual hosting
        # both break.
        pinned = _swap_host(parts, addresses[0])
        sent = dict(headers or {})
        sent.setdefault("Host", parts.netloc.split("@")[-1])

        request = self._client.build_request(
            method,
            pinned,
            headers=sent,
            params=params,
            json=json,
            content=content,
            extensions={"sni_hostname": host},
        )
        response = await self._client.send(request, stream=True)
        try:
            body = await self._read_capped(response)
        finally:
            await response.aclose()

        return httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            content=body,
            request=request,
        )

    async def _read_capped(self, response: httpx.Response) -> bytes:
        """Stop at the cap while reading, not after.

        Checking Content-Length is not enough: it is supplied by the source, and
        a chunked response has none at all.
        """
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > self.max_response_bytes:
                raise ResponseTooLargeError(
                    f"response exceeded {self.max_response_bytes} bytes and was abandoned"
                )
            chunks.append(chunk)
        return b"".join(chunks)

    async def aclose(self) -> None:
        await self._client.aclose()


def _swap_host(parts: SplitResult, address: str) -> str:
    """Rebuild the URL against a specific address, keeping scheme, port and path."""
    literal = f"[{address}]" if ":" in address else address
    authority = f"{literal}:{parts.port}" if parts.port else literal
    return urlunsplit((parts.scheme, authority, parts.path, parts.query, parts.fragment))
