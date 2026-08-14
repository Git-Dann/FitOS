# ADR 0002 — Analytics store

Status: accepted · Date: 2026-08-14 · Phase: C

## Context

The platform holds roughly 1.4 M canonical records per demo tenant across 19 fact tables, and must
answer metric queries with a p95 under one second on a developer laptop while also running detector
scans over 90-day windows. Gaps, lifecycle and audit are transactional and belong elsewhere.

## Decision

ClickHouse for canonical facts, dimensions, metric observations, detector inputs and aggregates.
PostgreSQL for the control plane. The two planes are separate by design and joined only through the
governed query layer.

Physical rules: partition by `(organization_id, toYYYYMM(occurred_at))`; order by the real query
pattern, typically `(organization_id, location_id, occurred_at)`; `ReplacingMergeTree` on the source
natural key for idempotent re-ingestion; incremental materialized views for common aggregates;
projections only after profiling; explicit TTL and tiering; query row and time limits; the
organization filter injected by the query layer, never supplied by a caller.

## Alternatives considered

**PostgreSQL alone, with partitioning and columnar extensions.** One database, one backup story, one
skill set — genuinely attractive at this data volume, which is not large. Rejected on trajectory:
the detector framework scans wide windows across many dimension combinations, and the seeded tenant
is deliberately the *small* case. Retrofitting a columnar store after the semantic layer and
detectors are written against row-store performance characteristics is a much larger change than
starting with the split.

**DuckDB.** Excellent for local development and embarrassingly fast for this size. Rejected as the
primary store: single-writer, weak multi-tenant isolation and no natural hosted operational story.
Reconsider for local-only development if Compose startup becomes painful.

**BigQuery or Snowflake.** Rejected: no credible local development story, and the brief requires the
full stack to run from one command on a laptop.

## Consequences

- Two stores to operate, back up and test. Migration tests are needed for both, and ClickHouse
  materialized-view tests are a distinct CI job.
- Eventual consistency between planes: a gap in PostgreSQL references facts in ClickHouse. Gaps
  therefore carry denormalised display values so the inbox never joins across planes at read time.
- `ReplacingMergeTree` deduplicates asynchronously, so queries that must not see duplicates use
  `FINAL` or a deduplicating view. This is a real footgun and is called out in the data contracts.
- Local Compose gains a ClickHouse container; resource footprint on a laptop must be measured in
  Phase A, not assumed.
