"""Temporal workflows: determinism, retries, partial results and resumption.

Two kinds of test here, and both are needed.

The **static** ones read the workflow source and fail on anything
non-deterministic. They are cheap, they run everywhere, and they catch the
mistake at the moment it is written rather than the first time a worker
restarts mid-run — which in production is the worst possible moment to discover
that `datetime.now()` was called inside a workflow body.

The **live** ones run against a real Temporal server, because a workflow that
type-checks and looks deterministic can still deadlock, mis-handle a child
failure, or retry when it should not. They are skipped when no server is
reachable; `FITOS_REQUIRE_TEMPORAL=1` turns the skip into a failure so the
coverage cannot quietly disappear.
"""

from __future__ import annotations

import ast
import inspect
import os
import uuid
from typing import Any

import pytest
from fitos_worker import workflows as workflow_module
from fitos_worker.workflows import (
    ACTIVITY_RETRY,
    BackfillInput,
    BackfillWorkflow,
    ConnectorRunWorkflow,
    RunInput,
    _outcome,
)

TEMPORAL_TARGET = os.environ.get("FITOS_TEMPORAL_TARGET", "127.0.0.1:7233")
REQUIRE_TEMPORAL = bool(os.environ.get("FITOS_REQUIRE_TEMPORAL"))


# ---------------------------------------------------------------------------
# Determinism, checked statically
# ---------------------------------------------------------------------------

# Calls that must never appear inside a workflow body. Each one produces a
# different answer on replay, which makes the workflow diverge from the history
# Temporal is replaying — silently, and usually only under load.
FORBIDDEN_CALLS = {
    "datetime.now": "wall-clock time; use workflow.now()",
    "datetime.utcnow": "wall-clock time; use workflow.now()",
    "time.time": "wall-clock time; use workflow.now()",
    "time.sleep": "blocking sleep; use workflow.sleep()",
    "uuid.uuid4": "randomness; use workflow.uuid4()",
    "uuid4": "randomness; use workflow.uuid4()",
    "random.random": "randomness",
    "random.choice": "randomness",
    "open": "I/O belongs in an activity",
    "requests.get": "I/O belongs in an activity",
}


def _workflow_bodies() -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Every function decorated with @workflow.run, as an AST."""
    source = inspect.getsource(workflow_module)
    tree = ast.parse(source)
    found: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if not isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for decorator in item.decorator_list:
                rendered = ast.unparse(decorator)
                if "workflow.run" in rendered:
                    found.append((f"{node.name}.{item.name}", item))
    return found


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            names.add(ast.unparse(child.func))
    return names


def test_the_body_finder_actually_finds_the_workflows() -> None:
    """Guards the guard. A determinism check over zero bodies passes everything."""
    names = {name for name, _ in _workflow_bodies()}
    assert names == {"ConnectorRunWorkflow.run", "BackfillWorkflow.run"}, names


@pytest.mark.parametrize("case", _workflow_bodies(), ids=lambda c: c[0])
def test_no_workflow_body_calls_anything_non_deterministic(
    case: tuple[str, ast.AST],
) -> None:
    """RELEASE-BLOCKING. Determinism is what makes replay work.

    Temporal rebuilds a workflow's state by replaying its history. A call that
    returns something different the second time makes the replayed run diverge
    from the recorded one — and the symptom is a wedged workflow days later,
    not an error at the point of the mistake.
    """
    name, body = case
    called = _called_names(body)

    for forbidden, reason in FORBIDDEN_CALLS.items():
        assert forbidden not in called, f"{name} calls {forbidden}: {reason}"


@pytest.mark.parametrize("case", _workflow_bodies(), ids=lambda c: c[0])
def test_every_side_effect_in_a_workflow_goes_through_an_activity_or_child(
    case: tuple[str, ast.AST],
) -> None:
    """A workflow decides; an activity acts.

    Anything awaited in a workflow body must be an activity, a child workflow,
    or a Temporal primitive. Awaiting a plain coroutine that does I/O is the
    same determinism bug wearing different clothes.
    """
    name, body = case
    allowed_prefixes = (
        "workflow.execute_activity",
        "workflow.execute_child_workflow",
        "workflow.start_activity",
        "workflow.sleep",
        "workflow.wait_condition",
    )

    for node in ast.walk(body):
        if isinstance(node, ast.Await):
            rendered = ast.unparse(node.value)
            assert rendered.startswith(allowed_prefixes), (
                f"{name} awaits {rendered.split('(')[0]}, which is not an activity "
                f"or a child workflow"
            )


def test_the_forbidden_list_would_actually_catch_something() -> None:
    """Proves the check discriminates, rather than passing on an empty set.

    A synthetic body that calls datetime.now must be flagged; if it is not, the
    check above is decoration.
    """
    tree = ast.parse(
        "class Bad:\n    @workflow.run\n    async def run(self):\n        return datetime.now()\n"
    )
    body = next(
        item
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        for item in node.body
        if isinstance(item, ast.AsyncFunctionDef)
    )
    assert "datetime.now" in _called_names(body)


# ---------------------------------------------------------------------------
# The retry policy
# ---------------------------------------------------------------------------


def test_retries_are_bounded() -> None:
    """An unbounded retry turns a misconfiguration into a weekend of traffic."""
    assert ACTIVITY_RETRY.maximum_attempts is not None
    assert 1 < ACTIVITY_RETRY.maximum_attempts <= 10


def test_a_blocked_destination_is_never_retried() -> None:
    """An egress refusal is a decision, not a transient failure.

    Retrying it wastes ten minutes of backoff and tells the operator nothing
    they did not already know from the first attempt.
    """
    assert ACTIVITY_RETRY.non_retryable_error_types is not None
    assert "EgressBlockedError" in ACTIVITY_RETRY.non_retryable_error_types


def test_the_workflow_does_not_implement_its_own_retry_loop() -> None:
    """A retry loop in a workflow body re-executes on replay and multiplies.

    Which is how a rate-limited source turns into a banned client.
    """
    source = inspect.getsource(workflow_module)
    tree = ast.parse(source)
    for name, body in _workflow_bodies():
        for node in ast.walk(body):
            if isinstance(node, ast.While):
                pytest.fail(f"{name} contains a while loop; use the activity retry policy")
    assert tree is not None


# ---------------------------------------------------------------------------
# Outcome arithmetic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("failures", "total", "expected"),
    [
        (0, 3, "succeeded"),
        (1, 3, "partial"),
        (3, 3, "failed"),
        (0, 0, "succeeded"),
    ],
)
def test_a_partial_result_says_it_is_partial(failures: int, total: int, expected: str) -> None:
    """Not "succeeded with warnings". One resource lost out of three is not success."""
    assert _outcome(failures, total) == expected


# ---------------------------------------------------------------------------
# Against a real Temporal server
# ---------------------------------------------------------------------------


def _temporal_available() -> bool:
    import socket

    host, _, port = TEMPORAL_TARGET.partition(":")
    try:
        with socket.create_connection((host, int(port or 7233)), timeout=2):
            return True
    except OSError:
        return False


live = pytest.mark.skipif(
    not _temporal_available() and not REQUIRE_TEMPORAL,
    reason="Temporal is not reachable; set FITOS_REQUIRE_TEMPORAL=1 to make this a failure",
)


@live
async def test_a_run_workflow_completes_against_a_real_server() -> None:
    """A workflow that type-checks can still deadlock. Run it."""
    from fitos_worker.workflows import RunActivities
    from temporalio.client import Client
    from temporalio.worker import Worker

    calls: list[dict[str, Any]] = []
    recorded: list[dict[str, Any]] = []

    async def execute(payload: dict[str, Any]) -> dict[str, Any]:
        calls.append(payload)
        return {"records_read": 10, "records_written": 9, "records_quarantined": 1}

    async def record(summary: dict[str, Any]) -> None:
        recorded.append(summary)

    activities = RunActivities(execute=execute, record_run=record)
    client = await Client.connect(TEMPORAL_TARGET)
    queue = f"fitos-test-{uuid.uuid4().hex[:8]}"

    async with Worker(
        client,
        task_queue=queue,
        workflows=[ConnectorRunWorkflow, BackfillWorkflow],
        activities=[activities.extract_resource, activities.record_run_summary],
    ):
        result = await client.execute_workflow(
            ConnectorRunWorkflow.run,
            RunInput(
                organization_id=str(uuid.uuid4()),
                connection_id=str(uuid.uuid4()),
                connector_key="generic_rest",
                connector_version=1,
                resources=["orders", "refunds"],
                mapping_version=2,
            ),
            id=f"run-{uuid.uuid4()}",
            task_queue=queue,
        )

    assert result.outcome == "succeeded"
    assert result.records_read == 20
    assert result.records_quarantined == 2
    assert len(calls) == 2
    assert len(recorded) == 1
    # The rejected count reaches the run record. Silent rejection is prohibited.
    assert recorded[0]["records_quarantined"] == 2


@live
async def test_one_failing_resource_yields_a_partial_run_not_a_failed_one() -> None:
    """RELEASE GATE. A partial result says it is partial, through the real engine."""
    from fitos_worker.workflows import RunActivities
    from temporalio.client import Client
    from temporalio.exceptions import ApplicationError
    from temporalio.worker import Worker

    recorded: list[dict[str, Any]] = []

    async def execute(payload: dict[str, Any]) -> dict[str, Any]:
        if payload["resource"] == "refunds":
            # Non-retryable, so the test does not wait out six attempts.
            raise ApplicationError("the source went away", non_retryable=True)
        return {"records_read": 5, "records_written": 5, "records_quarantined": 0}

    async def record(summary: dict[str, Any]) -> None:
        recorded.append(summary)

    activities = RunActivities(execute=execute, record_run=record)
    client = await Client.connect(TEMPORAL_TARGET)
    queue = f"fitos-test-{uuid.uuid4().hex[:8]}"

    async with Worker(
        client,
        task_queue=queue,
        workflows=[ConnectorRunWorkflow, BackfillWorkflow],
        activities=[activities.extract_resource, activities.record_run_summary],
    ):
        result = await client.execute_workflow(
            ConnectorRunWorkflow.run,
            RunInput(
                organization_id=str(uuid.uuid4()),
                connection_id=str(uuid.uuid4()),
                connector_key="generic_rest",
                connector_version=1,
                resources=["orders", "refunds"],
                mapping_version=1,
            ),
            id=f"run-{uuid.uuid4()}",
            task_queue=queue,
        )

    assert result.outcome == "partial"
    assert result.records_written == 5, "the succeeding resource was rolled back"
    assert result.error is not None
    assert "refunds" in result.error
    assert recorded[0]["outcome"] == "partial"


@live
async def test_a_backfill_runs_every_window_exactly_once() -> None:
    """Fanned out per window so a failure costs one window, not the range."""
    from fitos_worker.workflows import RunActivities
    from temporalio.client import Client
    from temporalio.worker import Worker

    seen: list[str] = []

    bounds: list[tuple[str | None, str | None]] = []

    async def execute(payload: dict[str, Any]) -> dict[str, Any]:
        seen.append(payload["run_id"])
        bounds.append((payload.get("since"), payload.get("until")))
        return {"records_read": 3, "records_written": 3, "records_quarantined": 0}

    async def record(summary: dict[str, Any]) -> None:
        return None

    activities = RunActivities(execute=execute, record_run=record)
    client = await Client.connect(TEMPORAL_TARGET)
    queue = f"fitos-test-{uuid.uuid4().hex[:8]}"
    connection = str(uuid.uuid4())

    windows = [
        ("2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00"),
        ("2026-01-02T00:00:00+00:00", "2026-01-03T00:00:00+00:00"),
        ("2026-01-03T00:00:00+00:00", "2026-01-04T00:00:00+00:00"),
    ]

    async with Worker(
        client,
        task_queue=queue,
        workflows=[ConnectorRunWorkflow, BackfillWorkflow],
        activities=[activities.extract_resource, activities.record_run_summary],
    ):
        result = await client.execute_workflow(
            BackfillWorkflow.run,
            BackfillInput(
                organization_id=str(uuid.uuid4()),
                connection_id=connection,
                connector_key="generic_rest",
                connector_version=1,
                resource="orders",
                mapping_version=1,
                windows=windows,
            ),
            id=f"backfill-{uuid.uuid4()}",
            task_queue=queue,
        )

    assert result.completed_windows == 3
    assert result.failed_windows == 0
    assert result.records_written == 9
    # Deterministic per-window run ids, so a replay addresses the same run
    # record rather than creating a second one.
    assert len(set(seen)) == 3, f"a window ran twice or ids collided: {seen}"
    assert all(run_id.startswith(connection) for run_id in seen)

    # Each window bounds its own extract. Without this the fan-out is pointless:
    # every window would re-read the same range.
    assert sorted(bounds) == sorted(windows), bounds


@live
async def test_a_failing_window_does_not_abandon_the_rest_of_the_backfill() -> None:
    """A backfill that stops at the first bad day leaves a silent hole."""
    from fitos_worker.workflows import RunActivities
    from temporalio.client import Client
    from temporalio.exceptions import ApplicationError
    from temporalio.worker import Worker

    async def execute(payload: dict[str, Any]) -> dict[str, Any]:
        if "2026-01-02" in payload["run_id"]:
            raise ApplicationError("that day is missing at the source", non_retryable=True)
        return {"records_read": 2, "records_written": 2, "records_quarantined": 0}

    async def record(summary: dict[str, Any]) -> None:
        return None

    activities = RunActivities(execute=execute, record_run=record)
    client = await Client.connect(TEMPORAL_TARGET)
    queue = f"fitos-test-{uuid.uuid4().hex[:8]}"

    async with Worker(
        client,
        task_queue=queue,
        workflows=[ConnectorRunWorkflow, BackfillWorkflow],
        activities=[activities.extract_resource, activities.record_run_summary],
    ):
        result = await client.execute_workflow(
            BackfillWorkflow.run,
            BackfillInput(
                organization_id=str(uuid.uuid4()),
                connection_id=str(uuid.uuid4()),
                connector_key="generic_rest",
                connector_version=1,
                resource="orders",
                mapping_version=1,
                windows=[
                    ("2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00"),
                    ("2026-01-02T00:00:00+00:00", "2026-01-03T00:00:00+00:00"),
                    ("2026-01-03T00:00:00+00:00", "2026-01-04T00:00:00+00:00"),
                ],
            ),
            id=f"backfill-{uuid.uuid4()}",
            task_queue=queue,
        )

    # The middle window failed as a run; the run workflow reports partial rather
    # than raising, so the backfill counts it as completed-with-nothing-written.
    assert result.completed_windows + result.failed_windows == 3
    assert result.records_written == 4, "the other two windows did not complete"
    assert result.outcome in {"partial", "succeeded"}
