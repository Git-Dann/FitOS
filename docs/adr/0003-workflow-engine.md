# ADR 0003 — Workflow engine

Status: accepted · Date: 2026-08-14 · Phase: C

## Context

Connector runs are long, external, rate-limited and failure-prone. Backfills span months and must
resume after a worker restart without duplicating rows. Detector runs are scheduled, must be
replayable at a pinned version, and must report progress to the UI. Partial failure of one resource
must not roll back another that succeeded.

## Decision

Temporal for durable connector runs, backfills, cleansing jobs, detector runs, retries, schedules,
cancellation and progress reporting. `dlt` for REST extraction, pagination, auth, incremental state,
merge and schema handling, wrapped behind the connector SDK so no product code imports a dlt type.

Workflows are deterministic and hold no I/O; activities do the work. Each activity has bounded
retries, exponential backoff with jitter, rate-limit handling, timeout, an idempotency strategy,
checkpointing, structured errors and propagated trace context.

## Alternatives considered

**Celery or RQ with a database-backed job table.** Familiar and light. Rejected: durable execution,
resumable long-running backfills and replayable runs would all have to be hand-built, and hand-built
resumption is exactly where duplicate-row bugs live.

**Prefect or Dagster.** Strong data-pipeline ergonomics and good lineage. Rejected as a poor fit for
the non-pipeline half of the workload — webhook-triggered ingestion, cancellation from the UI, and
per-run progress streaming — and Dagster's asset model would compete with dbt for ownership of the
transformation graph.

**Cron plus idempotent scripts.** Rejected: no cancellation, no progress, no replay at a pinned
version, and no per-resource partial-failure semantics.

## Consequences

- Temporal adds a service and a database to local Compose. Startup cost on a laptop is measured in
  Phase A.
- Workflow determinism constrains code: no wall-clock time, no randomness, no direct I/O in workflow
  bodies. Reviewers must know this, so it goes in `CLAUDE.md`.
- Versioning matters: changing a running workflow's shape requires Temporal's versioning API.
  Detector replay depends on it, so it is exercised deliberately in Phase D rather than discovered
  in production.
- Temporal workflow tests are a distinct test category in CI.
- Wrapping dlt costs an abstraction layer, and dlt's schema inference will occasionally want to do
  something the SDK's contract forbids. The wrapper is the right place to lose that argument
  explicitly rather than leak inference behaviour into canonical data.
