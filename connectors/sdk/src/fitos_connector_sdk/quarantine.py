"""Rejected records, kept rather than dropped.

"No silent failure" is a rule in CLAUDE.md, and this is the machinery that makes
it structural instead of a habit. A record that fails validation is quarantined
with its source reference, its failure list and the mapping version that
rejected it. Nothing is dropped, and a run that rejected records says so in its
summary even when nobody asks.

The failure reasons are a **closed enumeration**, taken from the data contract.
That matters more than it looks: a free-text reason cannot be counted, cannot be
charted, and cannot drive the `data_completeness` metric. Making the reasons a
fixed set is what lets a data-quality gap be detected by the same machinery as
a business gap — which is the point of having `data_freshness` and
`data_completeness` as first-class metrics rather than dashboard decorations.

A quarantined record is not a dead end. It carries enough to be re-run: the raw
reference, the source record id, and the mapping version. When a mapping is
corrected, the fix is a new version applied forward over the same raw objects —
which is why `mapping_version` is on the record rather than implied by when it
was written.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class QualityFlag(StrEnum):
    """The closed enumeration from docs/data-contracts.md §6.

    Adding a value here is a deliberate contract change, not a convenience. If
    a new failure does not fit, that is a signal the taxonomy is wrong, not a
    reason to add free text.
    """

    LATE_ARRIVAL = "late_arrival"
    OUT_OF_RANGE = "out_of_range"
    MISSING_REQUIRED = "missing_required"
    TYPE_COERCED = "type_coerced"
    DUPLICATE_SOURCE_ID = "duplicate_source_id"
    UNKNOWN_ENUM = "unknown_enum"
    FUTURE_DATED = "future_dated"
    NEGATIVE_AMOUNT = "negative_amount"
    CURRENCY_MISMATCH = "currency_mismatch"
    SCHEMA_DRIFT = "schema_drift"


class QuarantineReason(BaseModel):
    """One specific thing wrong with one record.

    `flag` is countable; `detail` and `field` are for the human who has to fix
    it. Both matter — a count with no detail cannot be acted on, and a detail
    with no count cannot be noticed.
    """

    model_config = ConfigDict(extra="forbid")

    flag: QualityFlag
    field: str | None = None
    detail: str = ""


class QuarantinedRecord(BaseModel):
    """A rejection, with everything needed to understand and re-run it."""

    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    connector_key: str
    resource: str
    source_record_id: str
    raw_ref: str
    mapping_version: int
    reasons: list[QuarantineReason] = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    quarantined_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def flags(self) -> list[QualityFlag]:
        return [reason.flag for reason in self.reasons]


class RunOutcome(StrEnum):
    """A partial result says it is partial.

    `PARTIAL` exists because one resource failing must not roll back another
    that succeeded, and must not be reported as success either. A run that read
    three resources and lost one is not a success with a footnote.
    """

    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


class ResourceOutcome(BaseModel):
    resource: str
    outcome: RunOutcome
    records_read: int = 0
    records_written: int = 0
    records_quarantined: int = 0
    error: str | None = None


class RunSummary(BaseModel):
    """What a run records. The quarantine count is never optional.

    Every field here answers a question somebody asks during an incident: which
    versions produced this, how much came in, how much was rejected, how long
    did rate limiting cost, and what is the trace to follow.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    organization_id: UUID
    connector_key: str
    connector_version: int
    mapping_version: int
    outcome: RunOutcome
    resources: list[ResourceOutcome] = Field(default_factory=list)
    started_at: datetime
    finished_at: datetime | None = None
    rate_limit_waits: int = 0
    rate_limit_seconds: float = 0.0
    retries: int = 0
    trace_id: str = ""
    secrets_used: list[str] = Field(default_factory=list)
    error: str | None = None

    @property
    def records_read(self) -> int:
        return sum(resource.records_read for resource in self.resources)

    @property
    def records_written(self) -> int:
        return sum(resource.records_written for resource in self.resources)

    @property
    def records_quarantined(self) -> int:
        return sum(resource.records_quarantined for resource in self.resources)

    def describe(self) -> str:
        """A one-line summary that always states the rejected count.

        Stating zero explicitly is the point. "12,400 records" and
        "12,400 records, 0 rejected" read the same to a machine and very
        differently to a person deciding whether to trust a number.
        """
        return (
            f"{self.outcome.value}: {self.records_read} read, "
            f"{self.records_written} written, {self.records_quarantined} rejected"
        )
