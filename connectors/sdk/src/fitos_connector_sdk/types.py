"""The connector contract, as types.

Product code depends on these and never on a `dlt` type or a vendor client.
That boundary is what makes the extraction library replaceable and what stops a
vendor's pagination model leaking into the canonical layer.

Two shapes here are load-bearing rather than convenient:

`SourceRecord` carries `raw_ref` from the moment it exists. The raw object is
written before parsing, so every record can point at the bytes it came from,
and a canonical row can be traced back to them. A record that cannot say where
it came from cannot produce evidence, and a gap without evidence is not
allowed to exist.

`Checkpoint` is opaque to the runner and meaningful only to the connector that
wrote it. The runner's job is to persist it and hand it back; the moment the
runner starts interpreting cursor contents, resumption becomes a shared
concern between two components that release separately.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AuthType(StrEnum):
    API_KEY = "api_key"
    OAUTH2 = "oauth2"
    HMAC_WEBHOOK = "hmac_webhook"
    FILE_UPLOAD = "file_upload"
    BASIC = "basic"


class ConnectionStatus(StrEnum):
    """The states a connection card may show.

    `FIXTURE` is a first-class state, not a variety of healthy. A connector
    replaying recorded data is useful and honest; a connector replaying
    recorded data while showing green is a lie the demo tells the buyer.
    """

    CONFIGURED = "configured"
    TESTING = "testing"
    SYNCING = "syncing"
    HEALTHY = "healthy"
    DELAYED = "delayed"
    SCHEMA_CHANGED = "schema_changed"
    FAILED = "failed"
    DISABLED = "disabled"
    FIXTURE = "fixture"


class RateLimitKind(StrEnum):
    LEAKY_BUCKET = "leaky_bucket"
    FIXED_WINDOW = "fixed_window"
    CONCURRENCY = "concurrency"
    NONE = "none"


class RateLimitModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: RateLimitKind
    capacity: int = Field(default=1, ge=1)
    restore_per_second: float = Field(default=1.0, gt=0)


class ConnectorManifest(BaseModel):
    """Declared capability. Validated in CI; a connector without one fails the build.

    `extra="forbid"` so a typo in a manifest key is an error rather than a
    silently ignored setting — `supports_backfil: true` would otherwise read as
    "backfill unsupported" and nobody would find out until a backfill was asked
    for.
    """

    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,62}$")
    name: str = Field(min_length=1, max_length=100)
    category: str
    version: int = Field(ge=1)
    auth_type: AuthType
    supported_resources: list[str] = Field(min_length=1)
    supports_backfill: bool = False
    supports_incremental: bool = False
    supports_webhooks: bool = False
    supports_schema_inspection: bool = False
    rate_limit_model: RateLimitModel
    required_secrets: list[str] = Field(default_factory=list)
    optional_settings: list[str] = Field(default_factory=list)
    canonical_targets: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("canonical_targets")
    @classmethod
    def _targets_name_declared_resources(
        cls, value: dict[str, list[str]], info: Any
    ) -> dict[str, list[str]]:
        declared = set(info.data.get("supported_resources") or [])
        unknown = set(value) - declared
        if unknown:
            raise ValueError(
                f"canonical_targets names resources that are not supported: {sorted(unknown)}"
            )
        return value


class ValidationProblem(BaseModel):
    field: str
    message: str


class ValidationResult(BaseModel):
    ok: bool
    problems: list[ValidationProblem] = Field(default_factory=list)

    @classmethod
    def failure(cls, *problems: ValidationProblem) -> ValidationResult:
        return cls(ok=False, problems=list(problems))

    @classmethod
    def success(cls) -> ValidationResult:
        return cls(ok=True)


class CredentialTestResult(BaseModel):
    """Fails closed. `ok=False` with a reason, never an exception carrying a secret."""

    ok: bool
    detail: str = ""
    checked_at: datetime | None = None


class ResourceDescriptor(BaseModel):
    key: str
    name: str
    supports_incremental: bool = False


class FieldDescriptor(BaseModel):
    name: str
    type: str
    nullable: bool = True


class SourceSchema(BaseModel):
    resource: str
    fields: list[FieldDescriptor]
    version: str = "1"


class BackfillRequest(BaseModel):
    resource: str
    start: datetime
    end: datetime


class BackfillWindow(BaseModel):
    start: datetime
    end: datetime


class BackfillPlan(BaseModel):
    """Deterministic for a fixed request. Contract test 5 asserts exactly that.

    A plan that varies run to run cannot be resumed, because resuming means
    knowing which windows are already done.
    """

    resource: str
    windows: list[BackfillWindow]

    @property
    def window_count(self) -> int:
        return len(self.windows)


class ExtractRequest(BaseModel):
    resource: str
    since: datetime | None = None
    until: datetime | None = None
    checkpoint: Checkpoint | None = None


class SourceRecord(BaseModel):
    """One record as the source gave it, plus where it came from.

    `raw_ref` is required. The raw object is written before parsing, so there is
    always something to point at, and a record with no provenance cannot become
    evidence for a gap.
    """

    source_record_id: str
    payload: dict[str, Any]
    raw_ref: str
    occurred_at: datetime | None = None
    received_at: datetime | None = None


class RecordBatch(BaseModel):
    """A unit of progress, not just a unit of transfer.

    Extraction yields batches so a long backfill checkpoints as it goes and a
    worker restart resumes rather than starts again. The checkpoint travels with
    the batch it follows, so persisting the batch and persisting the position
    is one decision instead of two that can disagree.
    """

    resource: str
    records: list[SourceRecord]
    checkpoint: Checkpoint | None = None
    raw_ref: str | None = None


class Checkpoint(BaseModel):
    """Opaque to the runner, meaningful to the connector.

    `cursor` is whatever the connector needs — a page token, a high-water mark,
    an offset. The runner persists it and hands it back; it never reads inside.
    """

    model_config = ConfigDict(extra="forbid")

    connector_key: str
    resource: str
    cursor: dict[str, Any] = Field(default_factory=dict)
    records_seen: int = 0


class WebhookVerification(BaseModel):
    """Signature checking. `ok=False` is the only acceptable answer to a bad one."""

    ok: bool
    reason: str = ""
    delivery_id: str | None = None


class HealthReport(BaseModel):
    status: ConnectionStatus
    detail: str = ""
    last_successful_run_at: datetime | None = None


class StagingMapping(BaseModel):
    """How a source record's fields land in the staging table.

    Held as data rather than code so a mapping can be versioned, previewed,
    compared and rolled back without a deploy — which is what makes a correction
    a forward operation rather than an edit of history.
    """

    resource: str
    target_table: str
    column_map: dict[str, str]
    required_columns: list[str] = Field(default_factory=list)


@runtime_checkable
class Connector(Protocol):
    """What every connector implements, Tier 1 and Tier 2 alike.

    Note what is absent: any method that creates an HTTP client, opens a socket
    or reads a secret directly. Those arrive on `ConnectorContext`, which is how
    the egress policy and the secret boundary are made unavoidable rather than
    advisory.
    """

    manifest: ConnectorManifest

    def validate_config(self, config: Mapping[str, Any]) -> ValidationResult: ...

    async def test_credentials(self, ctx: Any) -> CredentialTestResult: ...

    async def list_resources(self, ctx: Any) -> Sequence[ResourceDescriptor]: ...

    async def inspect_schema(self, ctx: Any, resource: str) -> SourceSchema: ...

    async def plan_backfill(self, ctx: Any, req: BackfillRequest) -> BackfillPlan: ...

    def extract(self, ctx: Any, req: ExtractRequest) -> AsyncIterator[RecordBatch]: ...

    def verify_webhook(
        self, ctx: Any, raw: bytes, headers: Mapping[str, str]
    ) -> WebhookVerification: ...

    def parse_webhook(self, ctx: Any, raw: bytes) -> Sequence[SourceRecord]: ...

    def staging_mapping(self, resource: str) -> StagingMapping: ...

    async def health(self, ctx: Any) -> HealthReport: ...

    def export_checkpoint(self) -> Checkpoint | None: ...

    def restore_checkpoint(self, checkpoint: Checkpoint) -> None: ...


# Resolves the forward references used above.
ExtractRequest.model_rebuild()
RecordBatch.model_rebuild()
