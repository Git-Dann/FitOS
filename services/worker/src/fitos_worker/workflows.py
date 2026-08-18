"""Temporal workflows for runs, backfills and retries.

The rule that governs every line here, from CLAUDE.md: **workflow bodies are
deterministic**. No wall-clock time, no randomness, no I/O. Temporal replays a
workflow's history to rebuild its state after a worker restart, so anything
non-deterministic produces a different decision on replay and the workflow
either wedges or silently diverges from what it did the first time.

That is why the code below looks the way it does:

- `workflow.now()` and `workflow.uuid4()`, never `datetime.now()` or `uuid4()`.
  The Temporal versions are recorded in history and replayed identically.
- Every side effect is an activity. Fetching, writing, and recording a run are
  all `execute_activity` calls; the workflow only decides *what* to do.
- Iteration order is fixed. Sorting or shuffling a list inside a workflow body
  changes the plan on replay if the input order ever differs.

The retry policy is on the activity, not a loop in the workflow. A hand-written
retry loop inside a workflow body re-executes on replay and multiplies attempts,
which is how a rate-limited source becomes a banned client.

Backfills fan out one child workflow per window rather than looping in one
workflow. A window that fails costs one window, the plan is deterministic so a
resumed backfill knows exactly which windows are done, and one enormous history
does not accumulate for a year-long range.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

# A source that is briefly unhappy should be retried; one that is permanently
# misconfigured should not be retried forever. Ten minutes of backoff, then the
# run fails visibly rather than retrying into the weekend.
ACTIVITY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=2),
    maximum_attempts=6,
    # An egress refusal and a config error are decisions, not transient
    # failures. Retrying them wastes ten minutes and tells nobody anything.
    non_retryable_error_types=["EgressBlockedError", "ValueError"],
)

EXTRACT_TIMEOUT = timedelta(hours=2)
SHORT_TIMEOUT = timedelta(minutes=5)


@dataclass
class RunInput:
    """What a run workflow is started with.

    Plain data, because Temporal serialises it into history. Anything with
    behaviour would not survive the round trip.
    """

    organization_id: str
    connection_id: str
    connector_key: str
    connector_version: int
    resources: list[str]
    mapping_version: int
    trigger: str = "manual"
    run_id: str | None = None
    # Bounds for an incremental or backfill run, as ISO-8601 strings because
    # workflow input is serialised into history. Absent means "everything the
    # connector considers new".
    since: str | None = None
    until: str | None = None


@dataclass
class WindowInput:
    """One backfill window."""

    organization_id: str
    connection_id: str
    connector_key: str
    connector_version: int
    resource: str
    mapping_version: int
    start: str
    end: str


@dataclass
class RunResult:
    run_id: str
    outcome: str
    records_read: int = 0
    records_written: int = 0
    records_quarantined: int = 0
    error: str | None = None


@dataclass
class BackfillInput:
    organization_id: str
    connection_id: str
    connector_key: str
    connector_version: int
    resource: str
    mapping_version: int
    windows: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class BackfillResult:
    completed_windows: int
    failed_windows: int
    records_written: int
    outcome: str


# ---------------------------------------------------------------------------
# Activities — everything that touches the world
# ---------------------------------------------------------------------------


class RunActivities:
    """Activity implementations, bound to their dependencies at worker start.

    A class rather than module functions so the worker can inject a session
    factory, a raw store and a connector registry without any of them becoming
    module-level state that tests have to work around.
    """

    def __init__(self, execute: Any, record_run: Any) -> None:
        self._execute = execute
        self._record_run = record_run

    @activity.defn(name="extract_resource")
    async def extract_resource(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run one connector over one resource. All the I/O lives here.

        Returns plain data because the result goes into workflow history.
        """
        return dict(await self._execute(payload))

    @activity.defn(name="record_run_summary")
    async def record_run_summary(self, summary: dict[str, Any]) -> None:
        """Persist the run record, including the rejected count.

        Its own activity so a failure to *record* a run does not look like a
        failure of the run itself — they have different causes and different
        fixes.
        """
        await self._record_run(summary)


# ---------------------------------------------------------------------------
# Workflows — decisions only
# ---------------------------------------------------------------------------


@workflow.defn(name="ConnectorRun")
class ConnectorRunWorkflow:
    """One run over one connection's resources.

    Resources are processed in the order given, and a failure in one does not
    abort the others: a partial result is a legitimate outcome and must be
    reported as partial rather than as success or as total failure.
    """

    @workflow.run
    async def run(self, payload: RunInput) -> RunResult:
        # workflow.uuid4, not uuid.uuid4. The latter would produce a different
        # id on replay, and the run record would disagree with itself.
        run_id = payload.run_id or str(workflow.uuid4())

        read = written = quarantined = 0
        failures: list[str] = []

        for resource in payload.resources:
            try:
                result = await workflow.execute_activity(
                    "extract_resource",
                    {
                        "run_id": run_id,
                        "organization_id": payload.organization_id,
                        "connection_id": payload.connection_id,
                        "connector_key": payload.connector_key,
                        "connector_version": payload.connector_version,
                        "resource": resource,
                        "mapping_version": payload.mapping_version,
                        # Passed through so a backfill window actually bounds
                        # the extract. Without them every window would re-read
                        # the same range and the fan-out would be pointless.
                        "since": payload.since,
                        "until": payload.until,
                    },
                    start_to_close_timeout=EXTRACT_TIMEOUT,
                    # Retry policy on the activity, never a loop here. A loop in
                    # a workflow body re-executes on replay and multiplies
                    # attempts, which is how a rate-limited source bans us.
                    retry_policy=ACTIVITY_RETRY,
                )
            except Exception as exc:
                failures.append(f"{resource}: {exc}")
                continue

            read += int(result.get("records_read", 0))
            written += int(result.get("records_written", 0))
            quarantined += int(result.get("records_quarantined", 0))

        outcome = _outcome(len(failures), len(payload.resources))

        await workflow.execute_activity(
            "record_run_summary",
            {
                "run_id": run_id,
                "organization_id": payload.organization_id,
                "connection_id": payload.connection_id,
                "connector_key": payload.connector_key,
                "connector_version": payload.connector_version,
                "mapping_version": payload.mapping_version,
                "trigger": payload.trigger,
                "outcome": outcome,
                "records_read": read,
                "records_written": written,
                "records_quarantined": quarantined,
                "error": "; ".join(failures) or None,
                # workflow.now(), not datetime.now(). Replay must produce the
                # same timestamp the first execution recorded.
                "finished_at": workflow.now().isoformat(),
            },
            start_to_close_timeout=SHORT_TIMEOUT,
            retry_policy=ACTIVITY_RETRY,
        )

        return RunResult(
            run_id=run_id,
            outcome=outcome,
            records_read=read,
            records_written=written,
            records_quarantined=quarantined,
            error="; ".join(failures) or None,
        )


@workflow.defn(name="Backfill")
class BackfillWorkflow:
    """A backfill, one child workflow per window.

    Fanned out rather than looped for three reasons: a failed window costs one
    window rather than the whole range; the plan is deterministic so a resumed
    backfill knows exactly which windows are done; and a year-long range does
    not accumulate one enormous workflow history.

    Windows run sequentially by default. A source with a rate limit does not
    benefit from parallel extraction — it just gets throttled harder — and the
    limiter lives per connection, so parallel windows would fight each other.
    """

    @workflow.run
    async def run(self, payload: BackfillInput) -> BackfillResult:
        completed = failed = written = 0

        # No sorting here. The plan arrives ordered, and re-sorting inside the
        # workflow would change the execution order on replay if the input
        # order ever differed.
        for start, end in payload.windows:
            try:
                result = await workflow.execute_child_workflow(
                    ConnectorRunWorkflow.run,
                    RunInput(
                        organization_id=payload.organization_id,
                        connection_id=payload.connection_id,
                        connector_key=payload.connector_key,
                        connector_version=payload.connector_version,
                        resources=[payload.resource],
                        mapping_version=payload.mapping_version,
                        trigger="backfill",
                        since=start,
                        until=end,
                        # Deterministic per window, so a replay addresses the
                        # same run record rather than creating a second one.
                        run_id=f"{payload.connection_id}:{payload.resource}:{start}",
                    ),
                    id=f"backfill-{payload.connection_id}-{payload.resource}-{start}",
                )
            except Exception:
                failed += 1
                continue

            completed += 1
            written += result.records_written

        return BackfillResult(
            completed_windows=completed,
            failed_windows=failed,
            records_written=written,
            outcome=_outcome(failed, completed + failed),
        )


def _outcome(failures: int, total: int) -> str:
    """Shared by both workflows so they cannot disagree about what partial means.

    A pure function with no I/O and no clock, safe to call from a workflow body.
    """
    if total == 0 or failures == 0:
        return "succeeded"
    if failures >= total:
        return "failed"
    return "partial"


WORKFLOWS = [ConnectorRunWorkflow, BackfillWorkflow]
