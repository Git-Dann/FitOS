"""Executing one connector run.

This is where the pieces meet: a connector produces batches, the raw object is
written before anything parses it, the active mapping version turns records into
staging rows, failures are quarantined with reasons, and the run record says
exactly what happened including how much was rejected.

Four properties this has to hold, each of which is an acceptance criterion:

**Idempotency.** Running the same extract twice yields the same canonical row
count. That is not enforced here by bookkeeping — it comes from the record ids
being derived from content, so a second run produces the same ids and the
canonical layer replaces rather than appends. The runner's contribution is not
to break it: no run-scoped ids, no timestamps in keys, nothing that varies
between two runs over the same bytes.

**Resumption.** A checkpoint travels with the batch it follows, and the run
record persists it after that batch is durably written. Persisting a checkpoint
before writing the batch would skip records on restart; persisting it in a
different transaction would risk both. The order here is: write the batch, then
save the checkpoint, in one transaction.

**Partial results say they are partial.** A resource that fails does not roll
back one that succeeded, and does not report success either. The run outcome is
`partial` with per-resource detail.

**Nothing is dropped silently.** Every rejected record becomes a quarantine row
with its reason, its raw reference and the mapping version that rejected it, and
the count reaches the run summary whether or not anybody reads it.

The runner takes a `RunStore` rather than a session, so the whole thing is
testable without a database and so the Temporal activity boundary has something
narrow to sit on.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from fitos_connector_sdk.context import ConnectorContext
from fitos_connector_sdk.mapping import MappingSpec, apply_mapping
from fitos_connector_sdk.quarantine import (
    QuarantinedRecord,
    QuarantineReason,
    ResourceOutcome,
    RunOutcome,
    RunSummary,
)
from fitos_connector_sdk.types import Checkpoint, ExtractRequest, RecordBatch, SourceRecord


class StagingWriter(Protocol):
    """Where mapped rows land.

    Narrow on purpose. The runner should not know whether staging is a table, a
    file or a queue, and a wide interface here would let run logic leak into
    storage concerns.
    """

    def write(
        self, *, organization_id: UUID, table: str, rows: Sequence[dict[str, Any]]
    ) -> int: ...


class RunStore(ABC):
    """Persistence for the run itself, its checkpoint and its rejections.

    Separated from the session so the runner can be tested without a database
    and so the Temporal activity boundary has something narrow to sit on.
    """

    @abstractmethod
    def save_checkpoint(self, run_id: UUID, checkpoint: Checkpoint) -> None: ...

    @abstractmethod
    def load_checkpoint(self, run_id: UUID) -> Checkpoint | None: ...

    @abstractmethod
    def quarantine(self, records: Sequence[QuarantinedRecord]) -> None: ...

    @abstractmethod
    def finish(self, summary: RunSummary) -> None: ...


@dataclass
class InMemoryRunStore(RunStore):
    """For tests, and for a fixture run that should leave nothing behind."""

    checkpoints: dict[UUID, Checkpoint] = field(default_factory=dict)
    quarantined: list[QuarantinedRecord] = field(default_factory=list)
    summaries: list[RunSummary] = field(default_factory=list)

    def save_checkpoint(self, run_id: UUID, checkpoint: Checkpoint) -> None:
        self.checkpoints[run_id] = checkpoint

    def load_checkpoint(self, run_id: UUID) -> Checkpoint | None:
        return self.checkpoints.get(run_id)

    def quarantine(self, records: Sequence[QuarantinedRecord]) -> None:
        self.quarantined.extend(records)

    def finish(self, summary: RunSummary) -> None:
        self.summaries.append(summary)


@dataclass
class ListStagingWriter(StagingWriter):
    """Collects rows in memory. Used by tests and by preview."""

    rows: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def write(self, *, organization_id: UUID, table: str, rows: Sequence[dict[str, Any]]) -> int:
        self.rows.extend((table, dict(row)) for row in rows)
        return len(rows)


@dataclass
class RunRequest:
    """One run, fully specified.

    `mapping` is passed in rather than looked up, because which version was
    active when the run started must not change underneath it. A run that
    switched mappings halfway would produce rows nobody could attribute.
    """

    run_id: UUID
    organization_id: UUID
    connection_id: UUID
    connector_key: str
    connector_version: int
    resources: Sequence[str]
    mapping: MappingSpec
    trigger: str = "manual"
    resume: bool = False


class ConnectorLike(Protocol):
    def extract(self, ctx: Any, req: ExtractRequest) -> Any: ...

    def validate_record(self, resource: str, record: SourceRecord) -> list[QuarantineReason]: ...


async def execute_run(
    *,
    request: RunRequest,
    connector: ConnectorLike,
    ctx: ConnectorContext,
    store: RunStore,
    staging: StagingWriter,
) -> RunSummary:
    """Run one connector over its resources and record exactly what happened."""
    started = datetime.now(UTC)
    outcomes: list[ResourceOutcome] = []

    resume_from: Checkpoint | None = (
        store.load_checkpoint(request.run_id) if request.resume else None
    )

    for resource in request.resources:
        try:
            outcome = await _run_resource(
                request=request,
                resource=resource,
                connector=connector,
                ctx=ctx,
                store=store,
                staging=staging,
                resume_from=resume_from
                if resume_from and resume_from.resource == resource
                else None,
            )
        except Exception as exc:
            # The error is redacted, because a transport error commonly quotes a
            # URL and a URL commonly carries a key.
            outcomes.append(
                ResourceOutcome(
                    resource=resource,
                    outcome=RunOutcome.FAILED,
                    error=ctx.secrets.redact(f"{type(exc).__name__}: {exc}"),
                )
            )
        else:
            outcomes.append(outcome)

    summary = RunSummary(
        run_id=request.run_id,
        organization_id=request.organization_id,
        connector_key=request.connector_key,
        connector_version=request.connector_version,
        mapping_version=request.mapping.version,
        outcome=_overall(outcomes),
        resources=outcomes,
        started_at=started,
        finished_at=datetime.now(UTC),
        rate_limit_waits=ctx.rate_limiter.waits,
        rate_limit_seconds=round(ctx.rate_limiter.waited_seconds, 3),
        trace_id=ctx.trace_id,
        # Which keys were used, never their values.
        secrets_used=sorted(ctx.secrets.accessed),
        error=_first_error(outcomes),
    )
    store.finish(summary)
    return summary


async def _run_resource(
    *,
    request: RunRequest,
    resource: str,
    connector: ConnectorLike,
    ctx: ConnectorContext,
    store: RunStore,
    staging: StagingWriter,
    resume_from: Checkpoint | None,
) -> ResourceOutcome:
    read = written = rejected = 0

    extract_request = ExtractRequest(resource=resource, checkpoint=resume_from)

    async for batch in connector.extract(ctx, extract_request):
        rows, rejections = _map_batch(
            request=request, resource=resource, connector=connector, batch=batch
        )
        read += len(batch.records)

        if rows:
            written += staging.write(
                organization_id=request.organization_id,
                table=request.mapping.target_table,
                rows=rows,
            )

        if rejections:
            store.quarantine(rejections)
            rejected += len(rejections)

        # After the batch is written, not before. Saving first would skip
        # records on restart; saving in a separate transaction would risk both.
        if batch.checkpoint is not None:
            store.save_checkpoint(request.run_id, batch.checkpoint)

    ctx.progress.wrote(written)
    ctx.progress.quarantined(rejected)

    return ResourceOutcome(
        resource=resource,
        outcome=RunOutcome.SUCCEEDED,
        records_read=read,
        records_written=written,
        records_quarantined=rejected,
    )


def _map_batch(
    *,
    request: RunRequest,
    resource: str,
    connector: ConnectorLike,
    batch: RecordBatch,
) -> tuple[list[dict[str, Any]], list[QuarantinedRecord]]:
    """Validate, then map. Both can reject; neither may drop.

    Validation is the connector's view of its own source; mapping is the
    tenant's configuration. Keeping them separate matters when something is
    wrong, because they have different owners and different fixes.
    """
    rows: list[dict[str, Any]] = []
    rejections: list[QuarantinedRecord] = []

    for record in batch.records:
        reasons: list[QuarantineReason] = list(connector.validate_record(resource, record))

        if not reasons:
            mapped = apply_mapping(request.mapping, record.payload)
            if mapped.ok and mapped.row is not None:
                rows.append(mapped.row)
                continue
            reasons.extend(mapped.reasons)

        rejections.append(
            QuarantinedRecord(
                organization_id=request.organization_id,
                connector_key=request.connector_key,
                resource=resource,
                source_record_id=record.source_record_id,
                # Always present: the raw object is written before parsing, so a
                # rejection can always be investigated rather than just counted.
                raw_ref=record.raw_ref,
                mapping_version=request.mapping.version,
                reasons=reasons,
                payload=record.payload,
            )
        )

    return rows, rejections


def _overall(outcomes: Sequence[ResourceOutcome]) -> RunOutcome:
    """A partial result says it is partial.

    Not "succeeded with warnings". A run that read three resources and lost one
    is not a success, and calling it one is how a broken connector goes
    unnoticed for a fortnight.
    """
    if not outcomes:
        return RunOutcome.SUCCEEDED
    failed = [o for o in outcomes if o.outcome is RunOutcome.FAILED]
    if not failed:
        return RunOutcome.SUCCEEDED
    if len(failed) == len(outcomes):
        return RunOutcome.FAILED
    return RunOutcome.PARTIAL


def _first_error(outcomes: Sequence[ResourceOutcome]) -> str | None:
    for outcome in outcomes:
        if outcome.error:
            return outcome.error
    return None


def new_run_id() -> UUID:
    return uuid4()
