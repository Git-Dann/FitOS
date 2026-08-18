"""The REST connector against the shared contract, plus network-specific risks.

This is the connector that actually makes requests, so it is where contract
test 14 has teeth and where the webhook gates (8 and 9) are exercised end to
end rather than at the helper level.
"""

from __future__ import annotations

import hashlib
import json
import socket
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fitos_connector_rest.connector import MANIFEST, RestConnector
from fitos_connector_sdk.context import ConnectorContext
from fitos_connector_sdk.contract_tests import ConnectorContractTests, ConnectorHarness
from fitos_connector_sdk.egress import EgressBlockedError, EgressPolicy
from fitos_connector_sdk.raw_store import FilesystemRawStore
from fitos_connector_sdk.types import ExtractRequest, SourceRecord
from fitos_connector_sdk.webhooks import (
    InMemoryDeliveryStore,
    accept_delivery,
    compute_signature,
)

ORG = uuid4()
SECRET = "webhook-secret-value"
API_KEY = "sk-live-do-not-log-me"

PAGE_ONE = {
    "data": [
        {"id": "r-1", "amount": 100, "occurred_at": "2026-05-01T10:00:00Z"},
        {"id": "r-2", "amount": 250, "occurred_at": "2026-05-01T10:01:00Z"},
    ],
    "next": "cursor-2",
}
PAGE_TWO = {
    "data": [{"id": "r-3", "amount": 700, "occurred_at": "2026-05-01T10:02:00Z"}],
    "next": None,
}


def _pin_dns(monkeypatch: pytest.MonkeyPatch, mapping: dict[str, list[str]]) -> None:
    def fake(host: str, *_a: Any, **_k: Any) -> list[Any]:
        if host not in mapping:
            raise socket.gaierror(f"no fixture for {host}")
        return [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 0))
            for address in mapping[host]
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake)


class _PagedTransport(httpx.AsyncBaseTransport):
    """Serves the two fixture pages, and records the requests it received."""

    def __init__(self, pages: list[dict[str, Any]] | None = None) -> None:
        self.pages = pages if pages is not None else [PAGE_ONE, PAGE_TWO]
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        cursor = request.url.params.get("cursor")
        page = self.pages[1] if cursor == "cursor-2" else self.pages[0]
        return httpx.Response(200, json=page)


def _context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    base_url: str = "https://api.example/v1/records",
    **overrides: Any,
) -> ConnectorContext:
    _pin_dns(monkeypatch, {"api.example": ["93.184.216.34"]})
    config: dict[str, Any] = {
        "base_url": base_url,
        "records_path": "data",
        "page_style": "cursor",
        "cursor_path": "next",
        "record_id_path": "id",
        "occurred_at_path": "occurred_at",
        "raw_store": FilesystemRawStore(tmp_path / "raw"),
    }
    config.update(overrides)
    return ConnectorContext.create(
        organization_id=ORG,
        connection_id=uuid4(),
        config=config,
        secrets={"api_key": API_KEY, "webhook_secret": SECRET},
        transport=transport or _PagedTransport(),
    )


def _signed(body: bytes, *, at: datetime | None = None) -> dict[str, str]:
    timestamp = str(int((at or datetime.now(UTC)).timestamp()))
    return {
        "X-Signature": compute_signature(SECRET, timestamp, body),
        "X-Timestamp": timestamp,
        "X-Delivery-Id": "delivery-abc",
    }


BODY = json.dumps({"id": "w-1", "amount": 500}).encode()


class TestRestContract(ConnectorContractTests):
    """The shared 14 points, including the ones CSV had to skip."""

    @pytest.fixture
    def harness(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ConnectorHarness:
        ctx = _context(monkeypatch, tmp_path)
        return ConnectorHarness(
            connector=RestConnector(),
            context=ctx,
            resource="records",
            organization_id=ORG,
            webhook_body=BODY,
            webhook_headers=_signed(BODY),
            tampered_body=json.dumps({"id": "w-1", "amount": 999999}).encode(),
            private_host_config={"base_url": "http://169.254.169.254/latest/meta-data/"},
            malformed_record=SourceRecord(
                source_record_id="future-1",
                payload={"id": "future-1"},
                raw_ref="inline:test",
                occurred_at=datetime.now(UTC) + timedelta(days=400),
            ),
            expected_flag="future_dated",
        )


# ---------------------------------------------------------------------------
# Egress — release gate 14, through the connector rather than the helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://127.0.0.1:8000/internal",
        "http://10.0.0.5/admin",
        "http://[::1]/",
        "file:///etc/passwd",
    ],
)
async def test_a_connector_aimed_at_a_forbidden_host_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, url: str
) -> None:
    """RELEASE GATE. The tenant supplies base_url; the tenant is not trusted."""
    ctx = _context(monkeypatch, tmp_path, base_url=url)
    with pytest.raises(EgressBlockedError):
        await RestConnector().test_credentials(ctx)


async def test_a_blocked_host_is_raised_not_reported_as_a_bad_credential(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Otherwise the operator spends an afternoon rotating a perfectly good key."""
    ctx = _context(monkeypatch, tmp_path, base_url="http://10.0.0.5/api")
    with pytest.raises(EgressBlockedError, match="private"):
        await RestConnector().test_credentials(ctx)


async def test_a_source_that_redirects_into_the_private_network_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RELEASE GATE. The source itself is the attacker in this one.

    base_url is perfectly legitimate and passes every check. The source then
    answers with a redirect to the metadata endpoint.
    """
    _pin_dns(
        monkeypatch,
        {"api.example": ["93.184.216.34"], "169.254.169.254": ["169.254.169.254"]},
    )

    class Redirecting(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                302, headers={"location": "http://169.254.169.254/latest/meta-data/"}
            )

    ctx = _context(monkeypatch, tmp_path, transport=Redirecting())
    with pytest.raises(EgressBlockedError, match="link-local"):
        await RestConnector().test_credentials(ctx)


# ---------------------------------------------------------------------------
# Idempotency — release gate 7
# ---------------------------------------------------------------------------


async def test_the_same_extract_twice_yields_the_same_record_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RELEASE GATE. A replay must collapse, not double."""
    connector = RestConnector()

    async def ids() -> list[str]:
        ctx = _context(monkeypatch, tmp_path)
        out: list[str] = []
        async for batch in connector.extract(ctx, ExtractRequest(resource="records")):
            out.extend(r.source_record_id for r in batch.records)
        return out

    assert await ids() == await ids() == ["r-1", "r-2", "r-3"]


async def test_a_source_with_no_id_field_still_produces_stable_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Minting a fresh id per run would double the canonical rows every sync."""
    pages = [{"data": [{"amount": 100}, {"amount": 250}], "next": None}]
    connector = RestConnector()

    async def ids() -> list[str]:
        ctx = _context(monkeypatch, tmp_path, transport=_PagedTransport(pages + pages))
        out: list[str] = []
        async for batch in connector.extract(ctx, ExtractRequest(resource="records")):
            out.extend(r.source_record_id for r in batch.records)
        return out

    first = await ids()
    assert first == await ids()
    assert all(i.startswith("sha256:") for i in first)


async def test_the_raw_page_is_stored_before_it_is_parsed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A quarantined record needs bytes to point at."""
    ctx = _context(monkeypatch, tmp_path)
    store = ctx.config["raw_store"]
    async for batch in RestConnector().extract(ctx, ExtractRequest(resource="records")):
        assert batch.raw_ref
        assert store.exists(batch.raw_ref)
        for record in batch.records:
            assert record.raw_ref == batch.raw_ref
        break


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


async def test_pagination_follows_the_cursor_to_the_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ctx = _context(monkeypatch, tmp_path)
    batches = [b async for b in RestConnector().extract(ctx, ExtractRequest(resource="records"))]
    assert [r.source_record_id for b in batches for r in b.records] == ["r-1", "r-2", "r-3"]


async def test_a_source_that_repeats_its_cursor_does_not_loop_forever(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The failure mode is a run that never ends, which nobody can act on.

    A source returning the same next-cursor on every page is a bug at the
    source, but it becomes our incident: the worker spins, the run never
    finishes, and no error is ever raised.
    """

    class Stuck(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.calls = 0

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            self.calls += 1
            return httpx.Response(200, json={"data": [{"id": "same"}], "next": "always"})

    stuck = Stuck()
    ctx = _context(monkeypatch, tmp_path, transport=stuck)
    batches = [b async for b in RestConnector().extract(ctx, ExtractRequest(resource="records"))]

    assert stuck.calls <= 3, "the connector kept requesting a repeating cursor"
    assert batches


async def test_an_empty_page_ends_page_number_pagination(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Trusting a total count instead loops forever whenever the count is stale."""

    class Numbered(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            page = int(request.url.params.get("page", "1"))
            data = [{"id": f"n-{page}"}] if page <= 2 else []
            return httpx.Response(200, json={"data": data, "total": 9999})

    ctx = _context(
        monkeypatch, tmp_path, transport=Numbered(), page_style="page_number", cursor_path=""
    )
    batches = [b async for b in RestConnector().extract(ctx, ExtractRequest(resource="records"))]
    ids = [r.source_record_id for b in batches for r in b.records]
    assert ids == ["n-1", "n-2"]


async def test_a_backfill_plan_covers_the_window_exactly_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from fitos_connector_sdk.types import BackfillRequest

    ctx = _context(monkeypatch, tmp_path)
    plan = await RestConnector().plan_backfill(
        ctx,
        BackfillRequest(
            resource="records",
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 5, tzinfo=UTC),
        ),
    )
    assert plan.window_count == 4
    assert plan.windows[0].start == datetime(2026, 1, 1, tzinfo=UTC)
    assert plan.windows[-1].end == datetime(2026, 1, 5, tzinfo=UTC)
    # No gaps and no overlaps — a backfill that misses a day is worse than one
    # that fails, because nothing reports it.
    for earlier, later in pairwise(plan.windows):
        assert earlier.end == later.start


# ---------------------------------------------------------------------------
# Webhooks — release gates 8 and 9
# ---------------------------------------------------------------------------


def test_a_valid_signature_is_accepted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ctx = _context(monkeypatch, tmp_path)
    result = RestConnector().verify_webhook(ctx, BODY, _signed(BODY))
    assert result.ok, result.reason
    assert result.delivery_id == "delivery-abc"


def test_a_tampered_body_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """RELEASE GATE 9. The signature is over the bytes, so changing them breaks it."""
    ctx = _context(monkeypatch, tmp_path)
    headers = _signed(BODY)
    result = RestConnector().verify_webhook(ctx, BODY.replace(b"500", b"99999"), headers)
    assert not result.ok
    assert result.reason == "signature mismatch"


def test_a_signature_from_the_wrong_secret_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ctx = _context(monkeypatch, tmp_path)
    timestamp = str(int(datetime.now(UTC).timestamp()))
    forged = {
        "X-Signature": compute_signature("not-the-secret", timestamp, BODY),
        "X-Timestamp": timestamp,
    }
    assert not RestConnector().verify_webhook(ctx, BODY, forged).ok


def test_a_stale_delivery_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Without a timestamp inside the signature, a captured delivery is valid forever."""
    ctx = _context(monkeypatch, tmp_path)
    old = datetime.now(UTC) - timedelta(hours=2)
    result = RestConnector().verify_webhook(ctx, BODY, _signed(BODY, at=old))
    assert not result.ok
    assert "tolerance" in result.reason


def test_a_future_dated_delivery_is_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A far-future timestamp would otherwise extend the replay window indefinitely."""
    ctx = _context(monkeypatch, tmp_path)
    ahead = datetime.now(UTC) + timedelta(hours=2)
    assert not RestConnector().verify_webhook(ctx, BODY, _signed(BODY, at=ahead)).ok


def test_missing_signature_headers_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ctx = _context(monkeypatch, tmp_path)
    assert not RestConnector().verify_webhook(ctx, BODY, {}).ok


def test_header_lookup_is_case_insensitive(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Proxies normalise header case differently; a miss here presents as an outage."""
    ctx = _context(monkeypatch, tmp_path)
    headers = {k.lower(): v for k, v in _signed(BODY).items()}
    assert RestConnector().verify_webhook(ctx, BODY, headers).ok


def test_the_same_delivery_twice_produces_one_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """RELEASE GATE 8, end to end: verify, dedupe, parse.

    Both deliveries verify — they are genuinely from the source. The dedupe
    store is what stops the second becoming a second fact.
    """
    ctx = _context(monkeypatch, tmp_path)
    connector = RestConnector()
    store = InMemoryDeliveryStore()
    headers = _signed(BODY)

    accepted_records: list[SourceRecord] = []
    for _ in range(2):
        verification = connector.verify_webhook(ctx, BODY, headers)
        assert verification.ok
        assert verification.delivery_id
        if accept_delivery(
            store=store,
            organization_id=ORG,
            connector_key=MANIFEST.key,
            delivery_id=verification.delivery_id,
        ):
            accepted_records.extend(connector.parse_webhook(ctx, BODY))

    assert len(accepted_records) == 1, "the retry created a second record"


def test_a_delivery_with_no_id_header_still_dedupes_on_content(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A source with no delivery header must not be able to replay the same bytes."""
    ctx = _context(monkeypatch, tmp_path)
    headers = _signed(BODY)
    headers.pop("X-Delivery-Id")
    result = RestConnector().verify_webhook(ctx, BODY, headers)
    assert result.ok
    assert result.delivery_id == hashlib.sha256(BODY).hexdigest()


# ---------------------------------------------------------------------------
# Secrets — contract test 13
# ---------------------------------------------------------------------------


async def test_a_transport_error_does_not_leak_the_api_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The realistic leak: an error quoting a URL that carries the key.

    Nobody writes `log(api_key)`. What happens is that a library raises an
    exception whose message contains the request URL, and the key is in the
    query string.
    """

    class Failing(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(f"could not connect to https://api.example/?key={API_KEY}")

    ctx = _context(monkeypatch, tmp_path, transport=Failing())
    result = await RestConnector().test_credentials(ctx)

    assert not result.ok
    assert API_KEY not in result.detail
    assert "[redacted:api_key]" in result.detail


def test_the_secret_resolver_never_renders_its_values() -> None:
    """A resolver that renders its contents ends up in the first traceback."""
    from fitos_connector_sdk.context import SecretResolver

    resolver = SecretResolver({"api_key": API_KEY})
    assert API_KEY not in repr(resolver)
    assert "api_key" in repr(resolver)


def test_the_resolver_records_which_keys_were_used_not_their_values() -> None:
    """So a run record can say what it used without ever holding one."""
    from fitos_connector_sdk.context import SecretResolver

    resolver = SecretResolver({"api_key": API_KEY, "unused": "x"})
    resolver.get("api_key")
    assert resolver.accessed == {"api_key"}


async def test_the_api_key_is_sent_as_a_header_not_a_query_string(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A key in a URL ends up in access logs, referrers and error messages."""
    transport = _PagedTransport()
    ctx = _context(monkeypatch, tmp_path, transport=transport)
    async for _ in RestConnector().extract(ctx, ExtractRequest(resource="records")):
        break

    request = transport.requests[0]
    assert API_KEY not in str(request.url)
    assert request.headers["authorization"] == f"Bearer {API_KEY}"


# ---------------------------------------------------------------------------
# Rate limiting — contract test 11
# ---------------------------------------------------------------------------


async def test_a_429_is_retried_rather_than_failing_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A busy source is not a broken connection."""

    class Throttling(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.calls = 0

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            self.calls += 1
            if self.calls == 1:
                return httpx.Response(429, json={})
            return httpx.Response(200, json={"data": [{"id": "r-1"}], "next": None})

    throttling = Throttling()
    ctx = _context(monkeypatch, tmp_path, transport=throttling)
    batches = [b async for b in RestConnector().extract(ctx, ExtractRequest(resource="records"))]

    assert throttling.calls == 2
    assert [r.source_record_id for b in batches for r in b.records] == ["r-1"]


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def test_a_cursor_style_without_a_cursor_path_is_rejected() -> None:
    """It would page once and silently stop, losing everything after page one."""
    result = RestConnector().validate_config(
        {"base_url": "https://api.example/", "records_path": "data", "page_style": "cursor"}
    )
    assert not result.ok
    assert any(p.field == "cursor_path" for p in result.problems)


def test_a_non_http_base_url_is_rejected_at_config_time() -> None:
    """Caught before a run starts rather than as a runtime egress refusal."""
    result = RestConnector().validate_config(
        {"base_url": "file:///etc/passwd", "records_path": "data"}
    )
    assert not result.ok
    assert any(p.field == "base_url" for p in result.problems)


async def test_schema_inspection_reports_the_keys_the_source_returned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ctx = _context(monkeypatch, tmp_path)
    schema = await RestConnector().inspect_schema(ctx, "records")
    assert {f.name for f in schema.fields} == {"id", "amount", "occurred_at"}
    assert {f.type for f in schema.fields} == {"string", "integer"}


def test_fixture_mode_is_never_reported_as_healthy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A connector card must show its real state."""
    import asyncio

    _pin_dns(monkeypatch, {"api.example": ["93.184.216.34"]})
    ctx = ConnectorContext.create(
        organization_id=ORG,
        connection_id=uuid4(),
        config={"base_url": "https://api.example/", "records_path": "data"},
        secrets={"api_key": API_KEY},
        egress=EgressPolicy(),
        fixture_mode=True,
    )
    report = asyncio.run(RestConnector().health(ctx))
    assert report.status.value == "fixture"
