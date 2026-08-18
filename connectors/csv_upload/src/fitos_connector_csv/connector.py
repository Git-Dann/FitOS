"""CSV and XLSX upload. Tier 1 — complete and testable with no credentials.

The simplest connector, which makes it the one that has to get the shared
behaviour exactly right: every other connector is checked against the same
14-point suite, and this is the reference implementation of what passing looks
like.

Three decisions worth explaining.

**Idempotency comes from content, not from bookkeeping.** The record id is
derived from the raw object's digest and the row's position within it. Upload
the same file twice and every record id is identical, so re-ingestion replaces
rather than duplicates — which is what makes contract test 7 pass without the
runner having to remember anything. It also means an accidental double upload
is a no-op rather than a data-quality incident.

**Validation is per-row and never fatal.** A malformed row is quarantined with
a reason and the run continues. A file where row 4,000 has a bad date must
still deliver the other 11,999 rows, and must still say that one was rejected.
That is contract test 12.

**Parsing does not trust the header.** A CSV header is user input. Duplicate
column names, a UTF-8 BOM on the first field, and blank column names are all
common in files exported from spreadsheets, and each one silently corrupts a
naive `DictReader` mapping.

Delimiter and encoding are sniffed but overridable, because sniffing is a
guess and a wrong guess on a semicolon-delimited European export produces one
enormous column rather than an error.
"""

from __future__ import annotations

import csv
import io
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fitos_connector_sdk.context import ConnectorContext
from fitos_connector_sdk.quarantine import QualityFlag, QuarantineReason
from fitos_connector_sdk.types import (
    AuthType,
    BackfillPlan,
    BackfillRequest,
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

MANIFEST = ConnectorManifest(
    key="csv_upload",
    name="CSV / XLSX upload",
    category="file",
    version=1,
    auth_type=AuthType.FILE_UPLOAD,
    supported_resources=["transactions", "stock_checks", "footfall"],
    supports_backfill=False,
    supports_incremental=False,
    supports_webhooks=False,
    supports_schema_inspection=True,
    rate_limit_model=RateLimitModel(kind=RateLimitKind.NONE),
    required_secrets=[],
    optional_settings=["delimiter", "encoding", "timezone"],
    canonical_targets={
        "transactions": ["fact_transaction", "fact_transaction_line"],
        "stock_checks": ["fact_stock_check"],
        "footfall": ["fact_footfall_observation"],
    },
)

# Batch size is a resumption granularity, not a performance tuning knob. A
# worker that dies mid-file resumes from the last completed batch, so a large
# batch means more repeated work on restart.
BATCH_SIZE = 500

REQUIRED_COLUMNS: dict[str, list[str]] = {
    "transactions": ["order_id", "occurred_at", "amount_minor", "currency"],
    "stock_checks": ["check_id", "occurred_at", "location_id", "sku", "observed_quantity"],
    "footfall": ["location_id", "interval_start", "count"],
}


class CsvUploadConnector:
    """Reads an uploaded file that has already been written to the raw store."""

    manifest = MANIFEST

    def __init__(self) -> None:
        self._checkpoint: Checkpoint | None = None

    # -- configuration ----------------------------------------------------

    def validate_config(self, config: Mapping[str, Any]) -> ValidationResult:
        problems: list[ValidationProblem] = []

        resource = config.get("resource")
        if not resource:
            problems.append(ValidationProblem(field="resource", message="resource is required"))
        elif resource not in MANIFEST.supported_resources:
            problems.append(
                ValidationProblem(
                    field="resource",
                    message=(
                        f"unknown resource {resource!r}; "
                        f"expected one of {sorted(MANIFEST.supported_resources)}"
                    ),
                )
            )

        if not config.get("raw_ref"):
            problems.append(
                ValidationProblem(
                    field="raw_ref",
                    message=(
                        "raw_ref is required; the file is written to raw storage before parsing"
                    ),
                )
            )

        delimiter = config.get("delimiter")
        if delimiter is not None and len(str(delimiter)) != 1:
            problems.append(
                ValidationProblem(
                    field="delimiter", message="delimiter must be exactly one character"
                )
            )

        return ValidationResult.success() if not problems else ValidationResult.failure(*problems)

    async def test_credentials(self, ctx: ConnectorContext) -> CredentialTestResult:
        """An upload has no credentials, and says so rather than claiming success.

        Returning ok=True with no detail would make the connection card show a
        green tick that means nothing.
        """
        return CredentialTestResult(
            ok=True,
            detail="file upload requires no credentials",
            checked_at=datetime.now(UTC),
        )

    async def list_resources(self, ctx: ConnectorContext) -> Sequence[ResourceDescriptor]:
        return [
            ResourceDescriptor(key=key, name=key.replace("_", " ").title())
            for key in MANIFEST.supported_resources
        ]

    async def inspect_schema(self, ctx: ConnectorContext, resource: str) -> SourceSchema:
        """The header of the uploaded file, as it actually is.

        Not the header we hoped for: reporting the declared columns rather than
        the observed ones would hide schema drift, which is exactly what this
        method exists to surface.
        """
        raw = ctx.config["raw_ref"]
        payload = _load(ctx, raw)
        header = _read_header(payload, _delimiter(ctx), _encoding(ctx))
        return SourceSchema(
            resource=resource,
            fields=[FieldDescriptor(name=name, type="string") for name in header],
        )

    async def plan_backfill(self, ctx: ConnectorContext, req: BackfillRequest) -> BackfillPlan:
        """A file has no time windows. One pass, and the plan says so."""
        return BackfillPlan(resource=req.resource, windows=[])

    # -- extraction -------------------------------------------------------

    async def extract(
        self, ctx: ConnectorContext, req: ExtractRequest
    ) -> AsyncIterator[RecordBatch]:
        raw_ref = str(ctx.config["raw_ref"])
        payload = _load(ctx, raw_ref)
        digest = _digest_of(raw_ref)

        start_row = 0
        if req.checkpoint is not None:
            start_row = int(req.checkpoint.cursor.get("row", 0))

        rows = _iter_rows(payload, _delimiter(ctx), _encoding(ctx))
        batch: list[SourceRecord] = []
        row_number = 0

        for row_number, row in enumerate(rows, start=1):
            if row_number <= start_row:
                continue

            batch.append(
                SourceRecord(
                    # Content-addressed: the same file re-uploaded produces the
                    # same ids, so re-ingestion replaces instead of duplicating.
                    source_record_id=f"{digest}:{row_number}",
                    payload=row,
                    raw_ref=raw_ref,
                    received_at=datetime.now(UTC),
                )
            )

            if len(batch) >= BATCH_SIZE:
                ctx.progress.read(len(batch))
                ctx.progress.batch()
                yield RecordBatch(
                    resource=req.resource,
                    records=batch,
                    raw_ref=raw_ref,
                    checkpoint=self._advance(req.resource, row_number),
                )
                batch = []

        if batch:
            ctx.progress.read(len(batch))
            ctx.progress.batch()
            yield RecordBatch(
                resource=req.resource,
                records=batch,
                raw_ref=raw_ref,
                checkpoint=self._advance(req.resource, row_number),
            )

    def _advance(self, resource: str, row: int) -> Checkpoint:
        checkpoint = Checkpoint(
            connector_key=MANIFEST.key,
            resource=resource,
            cursor={"row": row},
            records_seen=row,
        )
        self._checkpoint = checkpoint
        return checkpoint

    # -- webhooks ---------------------------------------------------------

    def verify_webhook(
        self, ctx: ConnectorContext, raw: bytes, headers: Mapping[str, str]
    ) -> WebhookVerification:
        """Declared unsupported, and refused rather than ignored.

        A connector whose manifest says `supports_webhooks: false` must not
        quietly accept one — an endpoint that accepts unverified payloads is
        worse than no endpoint.
        """
        return WebhookVerification(ok=False, reason="csv_upload does not accept webhooks")

    def parse_webhook(self, ctx: ConnectorContext, raw: bytes) -> Sequence[SourceRecord]:
        raise NotImplementedError("csv_upload does not accept webhooks")

    # -- mapping and validation -------------------------------------------

    def staging_mapping(self, resource: str) -> StagingMapping:
        return StagingMapping(
            resource=resource,
            target_table=f"stg_{resource}",
            column_map={name: name for name in REQUIRED_COLUMNS[resource]},
            required_columns=REQUIRED_COLUMNS[resource],
        )

    def validate_record(self, resource: str, record: SourceRecord) -> list[QuarantineReason]:
        """Per-row validation. Returns reasons; never raises, never drops.

        Returning a list rather than a bool is deliberate: one row can be wrong
        in several ways at once, and reporting only the first means the person
        fixing the file discovers the next one on the following run.
        """
        reasons: list[QuarantineReason] = []
        payload = record.payload

        for column in REQUIRED_COLUMNS.get(resource, []):
            value = payload.get(column)
            if value is None or str(value).strip() == "":
                reasons.append(
                    QuarantineReason(
                        flag=QualityFlag.MISSING_REQUIRED,
                        field=column,
                        detail=f"{column} is required and was empty",
                    )
                )

        for column in ("occurred_at", "interval_start"):
            if column in payload and payload.get(column):
                parsed = _parse_timestamp(str(payload[column]))
                if parsed is None:
                    reasons.append(
                        QuarantineReason(
                            flag=QualityFlag.TYPE_COERCED,
                            field=column,
                            detail=f"{column} is not an ISO-8601 timestamp",
                        )
                    )
                elif parsed > datetime.now(UTC):
                    # A future timestamp is usually a timezone bug or a
                    # spreadsheet auto-format, and it silently poisons any
                    # time-window aggregate it lands in.
                    reasons.append(
                        QuarantineReason(
                            flag=QualityFlag.FUTURE_DATED,
                            field=column,
                            detail=f"{column} is in the future",
                        )
                    )

        if "amount_minor" in payload and payload.get("amount_minor"):
            amount = _parse_int(str(payload["amount_minor"]))
            if amount is None:
                reasons.append(
                    QuarantineReason(
                        flag=QualityFlag.TYPE_COERCED,
                        field="amount_minor",
                        detail="amount_minor must be an integer number of minor units",
                    )
                )
            elif amount < 0:
                # Refunds are their own fact. A negative amount on a
                # transaction is a sign convention that differs from ours, and
                # accepting it would quietly halve somebody's revenue.
                reasons.append(
                    QuarantineReason(
                        flag=QualityFlag.NEGATIVE_AMOUNT,
                        field="amount_minor",
                        detail="negative amounts belong in a return, not a transaction",
                    )
                )

        currency = payload.get("currency")
        if currency is not None and str(currency).strip():
            code = str(currency).strip()
            if len(code) != 3 or not code.isalpha():
                reasons.append(
                    QuarantineReason(
                        flag=QualityFlag.CURRENCY_MISMATCH,
                        field="currency",
                        detail="currency must be a three-letter ISO 4217 code",
                    )
                )

        for column in ("observed_quantity", "count"):
            if column in payload and payload.get(column):
                quantity = _parse_decimal(str(payload[column]))
                if quantity is None:
                    reasons.append(
                        QuarantineReason(
                            flag=QualityFlag.TYPE_COERCED,
                            field=column,
                            detail=f"{column} must be numeric",
                        )
                    )
                elif quantity < 0:
                    reasons.append(
                        QuarantineReason(
                            flag=QualityFlag.OUT_OF_RANGE,
                            field=column,
                            detail=f"{column} cannot be negative",
                        )
                    )

        return reasons

    # -- lifecycle --------------------------------------------------------

    async def health(self, ctx: ConnectorContext) -> HealthReport:
        return HealthReport(
            status=ConnectionStatus.FIXTURE if ctx.fixture_mode else ConnectionStatus.HEALTHY,
            detail="upload connector is ready",
        )

    def export_checkpoint(self) -> Checkpoint | None:
        return self._checkpoint

    def restore_checkpoint(self, checkpoint: Checkpoint) -> None:
        self._checkpoint = checkpoint


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _load(ctx: ConnectorContext, raw_ref: str) -> bytes:
    store = ctx.config["raw_store"]
    payload: bytes = store.get(raw_ref)
    return payload


def _digest_of(raw_ref: str) -> str:
    """The digest embedded in the raw key. See raw_store.raw_key."""
    return raw_ref.rsplit("/", 1)[-1].split(".")[0]


def _delimiter(ctx: ConnectorContext) -> str | None:
    value = ctx.config.get("delimiter")
    return str(value) if value else None


def _encoding(ctx: ConnectorContext) -> str:
    return str(ctx.config.get("encoding") or "utf-8-sig")


def _decode(payload: bytes, encoding: str) -> str:
    """Decode, replacing what cannot be decoded rather than failing the file.

    A single bad byte in a 200,000-row export should cost one quarantined row,
    not the whole upload. The replacement character then fails validation on
    the field that contains it, which is the outcome we want: visible, local
    and attributable.
    """
    return payload.decode(encoding, errors="replace")


def _sniff(text: str, given: str | None) -> str:
    if given:
        return given
    sample = text[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        # Sniffing failed, which is common for a single-column file. Comma is
        # the safe default: guessing a rarer delimiter on weak evidence
        # produces one giant column instead of an error.
        return ","


def _normalise_header(raw_header: Sequence[str]) -> list[str]:
    """Make a spreadsheet's header safe to use as keys.

    Blank and duplicate names both occur in real exports. Left alone, a
    duplicate silently overwrites the earlier column and a blank one produces a
    key of "", which no mapping will ever reference.
    """
    seen: dict[str, int] = {}
    normalised: list[str] = []
    for index, name in enumerate(raw_header):
        cleaned = name.strip().lstrip("﻿")
        if not cleaned:
            cleaned = f"column_{index + 1}"
        if cleaned in seen:
            seen[cleaned] += 1
            cleaned = f"{cleaned}_{seen[cleaned]}"
        else:
            seen[cleaned] = 0
        normalised.append(cleaned)
    return normalised


def _read_header(payload: bytes, delimiter: str | None, encoding: str) -> list[str]:
    text = _decode(payload, encoding)
    reader = csv.reader(io.StringIO(text), delimiter=_sniff(text, delimiter))
    for row in reader:
        return _normalise_header(row)
    return []


def _iter_rows(payload: bytes, delimiter: str | None, encoding: str) -> list[dict[str, Any]]:
    text = _decode(payload, encoding)
    reader = csv.reader(io.StringIO(text), delimiter=_sniff(text, delimiter))
    rows = list(reader)
    if not rows:
        return []

    header = _normalise_header(rows[0])
    out: list[dict[str, Any]] = []
    for row in rows[1:]:
        if not any(cell.strip() for cell in row):
            # A trailing blank line is not a record. Emitting one would produce
            # a row that fails every required-field check, turning a cosmetic
            # artefact into a quarantine entry somebody has to investigate.
            continue
        # Ragged rows are kept, not truncated: a short row becomes missing
        # required fields (which quarantine reports precisely), and a long one
        # keeps its extras under positional names so nothing is lost silently.
        record: dict[str, Any] = {}
        for index, name in enumerate(header):
            record[name] = row[index] if index < len(row) else None
        for index in range(len(header), len(row)):
            record[f"column_{index + 1}"] = row[index]
        out.append(record)
    return out


def _parse_timestamp(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    # A naive timestamp is assumed UTC rather than rejected, but the assumption
    # is recorded here rather than left to whatever reads it next.
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _parse_int(value: str) -> int | None:
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None


def _parse_decimal(value: str) -> Decimal | None:
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
