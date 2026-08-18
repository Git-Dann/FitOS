"""The run executor, against the Phase C acceptance criteria.

Four of the criteria are properties of a run rather than of a connector, so they
are proven here: idempotency across two runs, a malformed record quarantined
while the run completes, a partial failure reported as partial, and a worker
restart resuming from checkpoint without duplicating rows.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fitos_connector_csv.connector import CsvUploadConnector
from fitos_connector_sdk.context import ConnectorContext
from fitos_connector_sdk.mapping import MappingSpec
from fitos_connector_sdk.quarantine import RunOutcome
from fitos_connector_sdk.raw_store import FilesystemRawStore
from fitos_connector_sdk.types import ExtractRequest, RecordBatch, SourceRecord
from fitos_worker.runner import (
    InMemoryRunStore,
    ListStagingWriter,
    RunRequest,
    execute_run,
    new_run_id,
)

ORG = uuid4()

CLEAN = b"""order_id,occurred_at,amount_minor,currency
A-1,2026-05-01T10:00:00Z,1250,GBP
A-2,2026-05-01T10:05:00Z,4300,GBP
A-3,2026-05-01T10:09:00Z,999,GBP
"""

MIXED = b"""order_id,occurred_at,amount_minor,currency
A-1,2026-05-01T10:00:00Z,1250,GBP
,2026-05-01T10:05:00Z,4300,GBP
A-3,2026-05-01T10:09:00Z,-500,GBP
A-4,2026-05-01T10:11:00Z,700,GBP
"""

MAPPING = MappingSpec(
    version=3,
    target_table="stg_transactions",
    column_map={
        "order_id": "order_id",
        "amount_minor": "amount_minor",
        "currency": "currency",
    },
    required_columns=("order_id", "amount_minor"),
    transforms={"amount_minor": ["to_int"], "currency": ["upper"]},
)


def _context(tmp_path: Path, payload: bytes) -> ConnectorContext:
    store = FilesystemRawStore(tmp_path / "raw")
    ref = store.put(
        organization_id=ORG,
        connector_key="csv_upload",
        resource="transactions",
        payload=payload,
        content_type="text/csv",
        extension="csv",
    )
    return ConnectorContext.create(
        organization_id=ORG,
        connection_id=uuid4(),
        config={"resource": "transactions", "raw_ref": ref.key, "raw_store": store},
    )


def _request(**overrides: Any) -> RunRequest:
    base: dict[str, Any] = {
        "run_id": new_run_id(),
        "organization_id": ORG,
        "connection_id": uuid4(),
        "connector_key": "csv_upload",
        "connector_version": 1,
        "resources": ["transactions"],
        "mapping": MAPPING,
    }
    base.update(overrides)
    return RunRequest(**base)


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


async def test_the_same_run_twice_writes_the_same_rows(tmp_path: Path) -> None:
    """RELEASE GATE. Running the same extract twice yields the same rows.

    Not merely the same count. Identical rows are what lets the canonical layer
    collapse a replay; the same count with different content is two versions of
    the truth.
    """
    connector = CsvUploadConnector()

    async def run() -> list[tuple[str, dict[str, Any]]]:
        staging = ListStagingWriter()
        await execute_run(
            request=_request(),
            connector=connector,
            ctx=_context(tmp_path / str(uuid4()), CLEAN),
            store=InMemoryRunStore(),
            staging=staging,
        )
        return staging.rows

    assert await run() == await run()


async def test_a_run_writes_to_the_table_the_mapping_names(tmp_path: Path) -> None:
    staging = ListStagingWriter()
    await execute_run(
        request=_request(),
        connector=CsvUploadConnector(),
        ctx=_context(tmp_path, CLEAN),
        store=InMemoryRunStore(),
        staging=staging,
    )
    assert {table for table, _ in staging.rows} == {"stg_transactions"}


async def test_the_mapping_is_applied_not_merely_recorded(tmp_path: Path) -> None:
    """The transforms have to run, or the staging row is raw strings."""
    staging = ListStagingWriter()
    await execute_run(
        request=_request(),
        connector=CsvUploadConnector(),
        ctx=_context(tmp_path, CLEAN),
        store=InMemoryRunStore(),
        staging=staging,
    )
    rows = [row for _, row in staging.rows]
    assert rows[0]["amount_minor"] == 1250
    assert isinstance(rows[0]["amount_minor"], int)
    assert rows[0]["currency"] == "GBP"


# ---------------------------------------------------------------------------
# Quarantine — the run still completes
# ---------------------------------------------------------------------------


async def test_a_malformed_record_is_quarantined_and_the_run_completes(
    tmp_path: Path,
) -> None:
    """RELEASE GATE. Two bad rows out of four; the other two still land."""
    store = InMemoryRunStore()
    staging = ListStagingWriter()

    summary = await execute_run(
        request=_request(),
        connector=CsvUploadConnector(),
        ctx=_context(tmp_path, MIXED),
        store=store,
        staging=staging,
    )

    assert summary.outcome is RunOutcome.SUCCEEDED
    assert summary.records_read == 4
    assert summary.records_written == 2
    assert summary.records_quarantined == 2
    assert len(staging.rows) == 2
    assert len(store.quarantined) == 2


async def test_every_quarantined_record_carries_a_reason_and_its_provenance(
    tmp_path: Path,
) -> None:
    """A rejection with no reason is a count nobody can act on.

    A rejection with no raw reference is one nobody can investigate, which is
    the same problem a step later.
    """
    store = InMemoryRunStore()
    await execute_run(
        request=_request(),
        connector=CsvUploadConnector(),
        ctx=_context(tmp_path, MIXED),
        store=store,
        staging=ListStagingWriter(),
    )

    for record in store.quarantined:
        assert record.reasons, "a quarantined record with no reason"
        assert record.raw_ref, "a quarantined record with no raw reference"
        assert record.mapping_version == MAPPING.version
        assert record.organization_id == ORG


async def test_the_rejected_count_is_reported_even_when_it_is_zero(
    tmp_path: Path,
) -> None:
    """ "12,400 records" and "12,400 records, 0 rejected" read very differently."""
    summary = await execute_run(
        request=_request(),
        connector=CsvUploadConnector(),
        ctx=_context(tmp_path, CLEAN),
        store=InMemoryRunStore(),
        staging=ListStagingWriter(),
    )
    assert summary.records_quarantined == 0
    assert "0 rejected" in summary.describe()


async def test_the_quarantine_reason_distinguishes_the_two_failures(
    tmp_path: Path,
) -> None:
    """A missing id and a negative amount have different fixes."""
    store = InMemoryRunStore()
    await execute_run(
        request=_request(),
        connector=CsvUploadConnector(),
        ctx=_context(tmp_path, MIXED),
        store=store,
        staging=ListStagingWriter(),
    )
    flags = {flag.value for record in store.quarantined for flag in record.flags}
    assert "missing_required" in flags
    assert "negative_amount" in flags


# ---------------------------------------------------------------------------
# Resumption
# ---------------------------------------------------------------------------


async def test_a_restart_resumes_from_the_checkpoint_without_duplicating(
    tmp_path: Path,
) -> None:
    """RELEASE GATE. A worker restart mid-run must not repeat or skip a row.

    The first run is interrupted after one batch, exactly as a killed worker
    would be. The second resumes from the persisted checkpoint, and the union
    has to equal an uninterrupted run — no row twice, none missing.
    """
    rows = b"order_id,occurred_at,amount_minor,currency\n" + b"".join(
        f"A-{i},2026-05-01T10:00:00Z,100,GBP\n".encode() for i in range(1200)
    )
    connector = CsvUploadConnector()
    ctx = _context(tmp_path, rows)

    complete = ListStagingWriter()
    await execute_run(
        request=_request(),
        connector=connector,
        ctx=_context(tmp_path / "whole", rows),
        store=InMemoryRunStore(),
        staging=complete,
    )

    # Interrupt after the first batch, keeping the checkpoint the way a real
    # crash would: written, because the batch it follows was written.
    store = InMemoryRunStore()
    interrupted = ListStagingWriter()
    run_id = new_run_id()
    batches = 0
    async for batch in connector.extract(ctx, ExtractRequest(resource="transactions")):
        interrupted.write(
            organization_id=ORG,
            table="stg_transactions",
            rows=[{"order_id": r.payload["order_id"]} for r in batch.records],
        )
        assert batch.checkpoint is not None
        store.save_checkpoint(run_id, batch.checkpoint)
        batches += 1
        if batches == 1:
            break

    assert batches == 1, "the interruption did not happen where the test expects"

    resumed = ListStagingWriter()
    await execute_run(
        request=_request(run_id=run_id, resume=True),
        connector=connector,
        ctx=ctx,
        store=store,
        staging=resumed,
    )

    recovered = [row["order_id"] for _, row in interrupted.rows] + [
        row["order_id"] for _, row in resumed.rows
    ]
    expected = [row["order_id"] for _, row in complete.rows]

    assert recovered == expected, "resuming changed the row set"
    assert len(set(recovered)) == len(recovered), "resuming duplicated a row"


async def test_the_checkpoint_is_saved_after_the_batch_not_before(
    tmp_path: Path,
) -> None:
    """Order matters, and the wrong order silently loses records.

    Saving the checkpoint first means a crash between the two leaves a position
    past records that were never written — and nothing ever reports it.
    """
    rows = b"order_id,occurred_at,amount_minor,currency\n" + b"".join(
        f"A-{i},2026-05-01T10:00:00Z,100,GBP\n".encode() for i in range(600)
    )

    observed: list[str] = []

    class RecordingStore(InMemoryRunStore):
        def save_checkpoint(self, run_id: Any, checkpoint: Any) -> None:
            observed.append("checkpoint")
            super().save_checkpoint(run_id, checkpoint)

    class RecordingStaging(ListStagingWriter):
        def write(self, *, organization_id: Any, table: str, rows: Any) -> int:
            observed.append("write")
            return super().write(organization_id=organization_id, table=table, rows=rows)

    await execute_run(
        request=_request(),
        connector=CsvUploadConnector(),
        ctx=_context(tmp_path, rows),
        store=RecordingStore(),
        staging=RecordingStaging(),
    )

    assert observed, "nothing was recorded"
    assert observed[0] == "write", "the checkpoint was saved before the batch was written"
    for earlier, later in pairwise(observed):
        if later == "checkpoint":
            assert earlier == "write", "a checkpoint was saved without a preceding write"


# ---------------------------------------------------------------------------
# Partial results
# ---------------------------------------------------------------------------


class _HalfBrokenConnector:
    """Succeeds on one resource and fails on another."""

    def __init__(self, good: str, bad: str) -> None:
        self.good = good
        self.bad = bad

    async def extract(self, ctx: Any, req: ExtractRequest) -> Any:
        if req.resource == self.bad:
            raise RuntimeError("the source went away")
        yield RecordBatch(
            resource=req.resource,
            records=[
                SourceRecord(
                    source_record_id="ok-1",
                    payload={"order_id": "A-1", "amount_minor": "100", "currency": "gbp"},
                    raw_ref="raw:1",
                )
            ],
            raw_ref="raw:1",
        )

    def validate_record(self, resource: str, record: SourceRecord) -> list[Any]:
        return []


async def test_one_resource_failing_does_not_roll_back_another(tmp_path: Path) -> None:
    """RELEASE GATE. A partial result says it is partial.

    Not "succeeded with warnings" and not "failed". The resource that worked
    keeps its rows; the one that did not is named with its error.
    """
    staging = ListStagingWriter()
    summary = await execute_run(
        request=_request(resources=["orders", "refunds"]),
        connector=_HalfBrokenConnector(good="orders", bad="refunds"),
        ctx=_context(tmp_path, CLEAN),
        store=InMemoryRunStore(),
        staging=staging,
    )

    assert summary.outcome is RunOutcome.PARTIAL
    assert len(staging.rows) == 1, "the successful resource was rolled back"

    by_resource = {o.resource: o for o in summary.resources}
    assert by_resource["orders"].outcome is RunOutcome.SUCCEEDED
    assert by_resource["refunds"].outcome is RunOutcome.FAILED
    assert by_resource["refunds"].error
    assert "went away" in by_resource["refunds"].error


async def test_every_resource_failing_is_a_failed_run(tmp_path: Path) -> None:
    summary = await execute_run(
        request=_request(resources=["refunds"]),
        connector=_HalfBrokenConnector(good="orders", bad="refunds"),
        ctx=_context(tmp_path, CLEAN),
        store=InMemoryRunStore(),
        staging=ListStagingWriter(),
    )
    assert summary.outcome is RunOutcome.FAILED
    assert summary.error


# ---------------------------------------------------------------------------
# The run record
# ---------------------------------------------------------------------------


async def test_the_run_record_names_the_versions_that_produced_it(
    tmp_path: Path,
) -> None:
    """Reproducing a number later needs connector version and mapping version."""
    summary = await execute_run(
        request=_request(),
        connector=CsvUploadConnector(),
        ctx=_context(tmp_path, CLEAN),
        store=InMemoryRunStore(),
        staging=ListStagingWriter(),
    )
    assert summary.connector_version == 1
    assert summary.mapping_version == 3
    assert summary.connector_key == "csv_upload"


async def test_the_run_record_lists_secret_keys_never_secret_values(
    tmp_path: Path,
) -> None:
    """A run record is readable by anyone with audit.view and is kept forever."""
    ctx = _context(tmp_path, CLEAN)
    ctx.secrets._values["api_key"] = "sk-live-should-not-appear"
    ctx.secrets.get("api_key")

    summary = await execute_run(
        request=_request(),
        connector=CsvUploadConnector(),
        ctx=ctx,
        store=InMemoryRunStore(),
        staging=ListStagingWriter(),
    )

    assert summary.secrets_used == ["api_key"]
    assert "sk-live-should-not-appear" not in summary.model_dump_json()


async def test_a_failure_message_is_redacted(tmp_path: Path) -> None:
    """The realistic leak: an exception quoting a URL carrying a key."""

    class _RaisingIterator:
        """An async iterator that fails on first use.

        Written as a real iterator rather than an async generator with a
        `yield` after the `raise`: that trick works, but the `yield` is dead
        code, and dead code in a test is a place a later reader looks for
        meaning that is not there.
        """

        def __aiter__(self) -> Any:
            return self

        async def __anext__(self) -> Any:
            raise RuntimeError("connect failed: https://api.example/?key=sk-live-secret")

    class Leaky:
        def extract(self, ctx: Any, req: ExtractRequest) -> Any:
            return _RaisingIterator()

        def validate_record(self, resource: str, record: SourceRecord) -> list[Any]:
            return []

    ctx = _context(tmp_path, CLEAN)
    ctx.secrets._values["api_key"] = "sk-live-secret"

    summary = await execute_run(
        request=_request(),
        connector=Leaky(),
        ctx=ctx,
        store=InMemoryRunStore(),
        staging=ListStagingWriter(),
    )

    assert summary.error is not None
    assert "sk-live-secret" not in summary.error
    assert "[redacted:api_key]" in summary.error


async def test_the_summary_is_recorded_even_when_the_run_fails(
    tmp_path: Path,
) -> None:
    """A failed run that records nothing is an outage with no starting point."""
    store = InMemoryRunStore()
    await execute_run(
        request=_request(resources=["refunds"]),
        connector=_HalfBrokenConnector(good="orders", bad="refunds"),
        ctx=_context(tmp_path, CLEAN),
        store=store,
        staging=ListStagingWriter(),
    )
    assert len(store.summaries) == 1
    assert store.summaries[0].outcome is RunOutcome.FAILED


@pytest.mark.parametrize("payload", [CLEAN, MIXED])
async def test_read_always_equals_written_plus_quarantined(tmp_path: Path, payload: bytes) -> None:
    """The arithmetic that makes silent dropping detectable.

    If a record can be read and neither written nor quarantined, it vanished —
    and no count would ever show it.
    """
    summary = await execute_run(
        request=_request(),
        connector=CsvUploadConnector(),
        ctx=_context(tmp_path, payload),
        store=InMemoryRunStore(),
        staging=ListStagingWriter(),
    )
    assert summary.records_read == summary.records_written + summary.records_quarantined
