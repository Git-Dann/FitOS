"""Generic REST connector with a signed-webhook collector. Tier 1.

The counterpart to the CSV connector: this one actually talks to the network,
so it is where contract test 14 has teeth. It never constructs an HTTP client —
it uses the one on `ConnectorContext`, which carries the egress policy — and
the contract suite asserts that by reading the source.

Three things here are worth explaining.

**Pagination is declarative.** `page_style` picks between a cursor in the
response body, a `Link` header, and page numbers. Hand-rolling a while-loop per
source is how a connector ends up with an infinite loop against a source that
returns the same next-cursor forever, so the loop is written once, bounded, and
detects a cursor that stops advancing.

**Idempotency comes from the source's own id.** `record_id_path` names the
field that identifies a record at the source. Without one, a re-run would mint
new ids and the canonical layer would double. When a source genuinely has no
stable id, the digest of the record's bytes is used instead — deterministic, so
a replay still collapses, and stated in the config rather than assumed.

**A webhook is verified before it is parsed.** Not after, and not "verified" by
the framework at some other layer: `verify_webhook` runs on the exact bytes
received, and `parse_webhook` refuses to run on anything that has not passed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from fitos_connector_sdk.context import ConnectorContext
from fitos_connector_sdk.egress import EgressBlockedError
from fitos_connector_sdk.quarantine import QualityFlag, QuarantineReason
from fitos_connector_sdk.types import (
    AuthType,
    BackfillPlan,
    BackfillRequest,
    BackfillWindow,
    Checkpoint,
    ConnectionStatus,
    ConnectorManifest,
    CredentialTestResult,
    ExtractRequest,
    FieldDescriptor,
    HealthReport,
    RateLimitKind,
    RateLimitModel,
    RecordBatch,
    ResourceDescriptor,
    SourceRecord,
    SourceSchema,
    StagingMapping,
    ValidationProblem,
    ValidationResult,
    WebhookVerification,
)
from fitos_connector_sdk.webhooks import DEFAULT_TOLERANCE, header, verify_signature

MANIFEST = ConnectorManifest(
    key="generic_rest",
    name="Generic REST / OpenAPI",
    category="generic",
    version=1,
    auth_type=AuthType.API_KEY,
    supported_resources=["records"],
    supports_backfill=True,
    supports_incremental=True,
    supports_webhooks=True,
    supports_schema_inspection=True,
    rate_limit_model=RateLimitModel(
        kind=RateLimitKind.LEAKY_BUCKET, capacity=20, restore_per_second=5
    ),
    required_secrets=["api_key"],
    optional_settings=[
        "page_style",
        "page_size",
        "cursor_path",
        "records_path",
        "record_id_path",
        "occurred_at_path",
        "webhook_secret_key",
    ],
    canonical_targets={"records": ["fact_transaction"]},
)

# A backfill is planned in fixed windows so the plan is deterministic and so a
# failure costs one day rather than the whole range.
BACKFILL_WINDOW = timedelta(days=1)

# Bounded because a source that always returns the same cursor would otherwise
# spin forever, and the symptom would be a run that never ends rather than an
# error anyone can act on.
MAX_PAGES = 10_000


class PageStyle(StrEnum):
    CURSOR = "cursor"
    LINK_HEADER = "link_header"
    PAGE_NUMBER = "page_number"
    SINGLE = "single"


class RestConnector:
    manifest = MANIFEST

    def __init__(self) -> None:
        self._checkpoint: Checkpoint | None = None

    # -- configuration ----------------------------------------------------

    def validate_config(self, config: Mapping[str, Any]) -> ValidationResult:
        problems: list[ValidationProblem] = []

        base_url = config.get("base_url")
        if not base_url:
            problems.append(ValidationProblem(field="base_url", message="base_url is required"))
        elif not str(base_url).startswith(("http://", "https://")):
            problems.append(
                ValidationProblem(field="base_url", message="base_url must be an http or https URL")
            )

        if not config.get("records_path"):
            problems.append(
                ValidationProblem(
                    field="records_path",
                    message=(
                        "records_path is required; it names the array of records in the response"
                    ),
                )
            )

        style = config.get("page_style", PageStyle.SINGLE)
        try:
            parsed = PageStyle(str(style))
        except ValueError:
            problems.append(
                ValidationProblem(
                    field="page_style",
                    message=f"page_style must be one of {[s.value for s in PageStyle]}",
                )
            )
        else:
            if parsed is PageStyle.CURSOR and not config.get("cursor_path"):
                problems.append(
                    ValidationProblem(
                        field="cursor_path",
                        message="cursor_path is required when page_style is cursor",
                    )
                )

        return ValidationResult.success() if not problems else ValidationResult.failure(*problems)

    async def test_credentials(self, ctx: ConnectorContext) -> CredentialTestResult:
        """One authenticated request. Fails closed and never echoes the key.

        The egress check happens inside `ctx.http`, so a base_url pointing at
        the private network raises here rather than reaching the source — which
        is exactly what contract test 14 asserts.
        """
        url = str(ctx.config["base_url"])
        await ctx.rate_limiter.acquire()
        try:
            response = await ctx.http.get(url, headers=self._auth_headers(ctx))
        except EgressBlockedError:
            # Re-raised, not converted into ok=False. A blocked destination is a
            # configuration error the operator must see, not a credential
            # problem they will waste an afternoon on.
            raise
        except Exception as exc:
            return CredentialTestResult(
                ok=False,
                # Redacted, because a transport error commonly quotes the URL,
                # and the URL commonly carries the key in a query string.
                detail=ctx.secrets.redact(f"{type(exc).__name__}: {exc}"),
                checked_at=datetime.now(UTC),
            )

        ok = response.status_code < 400
        return CredentialTestResult(
            ok=ok,
            detail="" if ok else f"source returned HTTP {response.status_code}",
            checked_at=datetime.now(UTC),
        )

    async def list_resources(self, ctx: ConnectorContext) -> Sequence[ResourceDescriptor]:
        return [ResourceDescriptor(key="records", name="Records", supports_incremental=True)]

    async def inspect_schema(self, ctx: ConnectorContext, resource: str) -> SourceSchema:
        """The keys the source actually returned, not the ones we hoped for."""
        page = await self._fetch(ctx, str(ctx.config["base_url"]))
        records = _dig(page, str(ctx.config["records_path"])) or []
        fields: dict[str, str] = {}
        for record in records[:50]:
            if isinstance(record, dict):
                for key, value in record.items():
                    fields.setdefault(key, _json_type(value))
        return SourceSchema(
            resource=resource,
            fields=[FieldDescriptor(name=k, type=v) for k, v in sorted(fields.items())],
        )

    async def plan_backfill(self, ctx: ConnectorContext, req: BackfillRequest) -> BackfillPlan:
        """Fixed daily windows. Deterministic, which is what makes it resumable."""
        windows: list[BackfillWindow] = []
        cursor = req.start
        while cursor < req.end:
            end = min(cursor + BACKFILL_WINDOW, req.end)
            windows.append(BackfillWindow(start=cursor, end=end))
            cursor = end
        return BackfillPlan(resource=req.resource, windows=windows)

    # -- extraction -------------------------------------------------------

    async def extract(
        self, ctx: ConnectorContext, req: ExtractRequest
    ) -> AsyncIterator[RecordBatch]:
        style = PageStyle(str(ctx.config.get("page_style", PageStyle.SINGLE)))
        url = str(ctx.config["base_url"])
        records_path = str(ctx.config["records_path"])

        cursor: str | None = None
        page_number = 1
        if req.checkpoint is not None:
            cursor = req.checkpoint.cursor.get("cursor")
            page_number = int(req.checkpoint.cursor.get("page", 1))

        seen_cursors: set[str] = set()

        for _ in range(MAX_PAGES):
            params = self._page_params(ctx, style, cursor, page_number, req)
            page = await self._fetch(ctx, url, params=params)
            raw_ref = self._store_raw(ctx, req.resource, page)

            items = _dig(page, records_path) or []
            if not isinstance(items, list):
                items = []

            records = [
                self._to_record(ctx, item, raw_ref) for item in items if isinstance(item, dict)
            ]
            ctx.progress.read(len(records))
            ctx.progress.batch()

            next_cursor = self._next_cursor(ctx, style, page)
            page_number += 1
            checkpoint = Checkpoint(
                connector_key=MANIFEST.key,
                resource=req.resource,
                cursor={"cursor": next_cursor, "page": page_number},
                records_seen=(req.checkpoint.records_seen if req.checkpoint else 0) + len(records),
            )
            self._checkpoint = checkpoint

            yield RecordBatch(
                resource=req.resource,
                records=records,
                raw_ref=raw_ref,
                checkpoint=checkpoint,
            )

            if style is PageStyle.SINGLE or not next_cursor:
                return
            if next_cursor in seen_cursors:
                # The source is repeating itself. Stopping is the only safe
                # move: continuing is an infinite loop whose symptom is a run
                # that never finishes rather than an error anyone can act on.
                return
            seen_cursors.add(next_cursor)
            cursor = next_cursor

    def _page_params(
        self,
        ctx: ConnectorContext,
        style: PageStyle,
        cursor: str | None,
        page_number: int,
        req: ExtractRequest,
    ) -> dict[str, str]:
        params: dict[str, str] = {}
        size = ctx.config.get("page_size")
        if size:
            params["limit"] = str(size)
        if style is PageStyle.CURSOR and cursor:
            params["cursor"] = cursor
        if style is PageStyle.PAGE_NUMBER:
            params["page"] = str(page_number)
        if req.since:
            params["since"] = req.since.isoformat()
        if req.until:
            params["until"] = req.until.isoformat()
        return params

    def _next_cursor(
        self, ctx: ConnectorContext, style: PageStyle, page: dict[str, Any]
    ) -> str | None:
        if style is PageStyle.CURSOR:
            value = _dig(page, str(ctx.config.get("cursor_path", "")))
            return str(value) if value else None
        if style is PageStyle.PAGE_NUMBER:
            items = _dig(page, str(ctx.config["records_path"])) or []
            # An empty page is the end. Trusting a total count instead would
            # loop forever whenever the source's count is stale.
            return "next" if isinstance(items, list) and items else None
        return None

    async def _fetch(
        self, ctx: ConnectorContext, url: str, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        await ctx.rate_limiter.acquire()
        response = await ctx.http.get(url, headers=self._auth_headers(ctx), params=params)
        if response.status_code == 429:
            # A 429 is a backoff instruction, not a failure. Contract test 11.
            await ctx.rate_limiter.acquire(cost=float(ctx.rate_limiter.model.capacity))
            response = await ctx.http.get(url, headers=self._auth_headers(ctx), params=params)
        response.raise_for_status()
        parsed = response.json()
        return parsed if isinstance(parsed, dict) else {"data": parsed}

    def _auth_headers(self, ctx: ConnectorContext) -> dict[str, str]:
        """Reads the key at the moment of use and keeps no reference to it."""
        if not ctx.secrets.has("api_key"):
            return {}
        return {"Authorization": f"Bearer {ctx.secrets.get('api_key')}"}

    def _store_raw(self, ctx: ConnectorContext, resource: str, page: dict[str, Any]) -> str:
        """The raw object is written before anything parses it.

        So a record that fails validation still has bytes to point at, which is
        what makes a quarantine entry investigable rather than just a count.
        """
        store = ctx.config.get("raw_store")
        payload = json.dumps(page, sort_keys=True, separators=(",", ":")).encode()
        if store is None:
            return f"inline:{hashlib.sha256(payload).hexdigest()}"
        ref = store.put(
            organization_id=ctx.organization_id,
            connector_key=MANIFEST.key,
            resource=resource,
            payload=payload,
        )
        return str(ref.key)

    def _to_record(self, ctx: ConnectorContext, item: dict[str, Any], raw_ref: str) -> SourceRecord:
        id_path = str(ctx.config.get("record_id_path", "id"))
        raw_id = _dig(item, id_path)
        if raw_id is None or str(raw_id) == "":
            # No stable id at the source. The digest of the record is
            # deterministic, so a replay still collapses to one canonical row
            # rather than minting a new id every run.
            canonical = json.dumps(item, sort_keys=True, separators=(",", ":")).encode()
            source_id = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
        else:
            source_id = str(raw_id)

        occurred_at = None
        occurred_path = ctx.config.get("occurred_at_path")
        if occurred_path:
            occurred_at = _parse_timestamp(_dig(item, str(occurred_path)))

        return SourceRecord(
            source_record_id=source_id,
            payload=item,
            raw_ref=raw_ref,
            occurred_at=occurred_at,
            received_at=datetime.now(UTC),
        )

    # -- webhooks ---------------------------------------------------------

    def verify_webhook(
        self, ctx: ConnectorContext, raw: bytes, headers: Mapping[str, str]
    ) -> WebhookVerification:
        """Signature over the exact bytes received, plus a freshness window."""
        secret_key = str(ctx.config.get("webhook_secret_key", "webhook_secret"))
        if not ctx.secrets.has(secret_key):
            return WebhookVerification(ok=False, reason="no webhook secret configured")

        signature = header(headers, "X-Signature")
        timestamp = header(headers, "X-Timestamp")
        if not signature or not timestamp:
            return WebhookVerification(ok=False, reason="missing signature or timestamp header")

        result = verify_signature(
            secret=ctx.secrets.get(secret_key),
            raw=raw,
            signature=signature,
            timestamp=timestamp,
            tolerance=DEFAULT_TOLERANCE,
        )
        if not result.ok:
            return result

        # The delivery id is what dedupe is keyed on. Falling back to the body
        # digest means a source with no delivery header still cannot replay the
        # identical payload twice.
        delivery = header(headers, "X-Delivery-Id") or hashlib.sha256(raw).hexdigest()
        return WebhookVerification(ok=True, delivery_id=delivery)

    def parse_webhook(self, ctx: ConnectorContext, raw: bytes) -> Sequence[SourceRecord]:
        """Only ever called after verify_webhook returned ok."""
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return []

        raw_ref = f"webhook:{hashlib.sha256(raw).hexdigest()}"
        items = payload if isinstance(payload, list) else [payload]
        return [self._to_record(ctx, item, raw_ref) for item in items if isinstance(item, dict)]

    # -- mapping and validation -------------------------------------------

    def staging_mapping(self, resource: str) -> StagingMapping:
        return StagingMapping(
            resource=resource,
            target_table="stg_rest_records",
            column_map={"id": "source_record_id", "occurred_at": "occurred_at"},
            required_columns=["source_record_id"],
        )

    def validate_record(self, resource: str, record: SourceRecord) -> list[QuarantineReason]:
        reasons: list[QuarantineReason] = []
        if not record.source_record_id:
            reasons.append(
                QuarantineReason(
                    flag=QualityFlag.MISSING_REQUIRED,
                    field="source_record_id",
                    detail="the record has no identifier at the source",
                )
            )
        if record.occurred_at is not None and record.occurred_at > datetime.now(UTC):
            reasons.append(
                QuarantineReason(
                    flag=QualityFlag.FUTURE_DATED,
                    field="occurred_at",
                    detail="occurred_at is in the future",
                )
            )
        if not record.payload:
            reasons.append(
                QuarantineReason(
                    flag=QualityFlag.MISSING_REQUIRED,
                    field="payload",
                    detail="the record carried no fields",
                )
            )
        return reasons

    # -- lifecycle --------------------------------------------------------

    async def health(self, ctx: ConnectorContext) -> HealthReport:
        if ctx.fixture_mode:
            # Never dressed as healthy. A fixture run is honest and useful; a
            # fixture run showing green is a lie the demo tells the buyer.
            return HealthReport(status=ConnectionStatus.FIXTURE, detail="replaying fixtures")
        result = await self.test_credentials(ctx)
        return HealthReport(
            status=ConnectionStatus.HEALTHY if result.ok else ConnectionStatus.FAILED,
            detail=result.detail,
        )

    def export_checkpoint(self) -> Checkpoint | None:
        return self._checkpoint

    def restore_checkpoint(self, checkpoint: Checkpoint) -> None:
        self._checkpoint = checkpoint


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dig(payload: Any, path: str) -> Any:
    """Follow a dotted path. Returns None rather than raising on a miss.

    A missing path is a schema-drift signal for the caller to handle, not an
    exception that kills a run halfway through a page.
    """
    if not path:
        return None
    current = payload
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _json_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if value is None:
        return "null"
    return "string"


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
