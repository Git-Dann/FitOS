# Architecture

Target architecture for the FitOS Gap Intelligence platform. Decisions with alternatives are
recorded as ADRs in [docs/adr/](adr/); this document is the assembled picture.

## 1. Repository layout

```text
apps/
  web/                  Next.js App Router product application
  storybook/            component and data-visualisation workshop
services/
  api/                  FastAPI control and product API
  worker/               Temporal workers: ingestion, mapping, detectors
  semantic/             Cube Core semantic layer
packages/
  ui/                   tokens, primitives, product components
  contracts/            generated TS contracts and shared schemas
  charts/               evidence-led visualisations
  demo/                 deterministic fixtures and scenario definitions
  config/               shared lint, TypeScript, test settings
connectors/
  sdk/ csv_upload/ rest_openapi/ webhook/ stripe/ shopify/ ga4/
  app_store_connect/ google_play/ retail_templates/
data/
  dbt/ seeds/ contracts/
infra/
  compose/ opentofu/ scripts/
docs/
legacy/
  fitos-prototype/      preserved prototype, moved with git mv
```

pnpm workspaces + Turborepo for JS/TS; `uv` with a locked file for Python. Both lockfiles committed.
See [ADR 0001](adr/0001-monorepo-and-package-manager.md).

## 2. Service topology

```text
                    ┌──────────────┐
  browser ─────────▶│  apps/web    │  Next.js — RSC for read surfaces,
                    │  (Node)      │  client components for tables/charts
                    └──────┬───────┘
                           │ generated OpenAPI client
                    ┌──────▼───────┐        ┌──────────────┐
                    │ services/api │───────▶│  PostgreSQL  │ control plane
                    │  (FastAPI)   │        └──────────────┘
                    └──┬────────┬──┘
        certified      │        │  enqueue / signal
        metric queries │        │
                ┌──────▼─────┐  │      ┌───────────────┐
                │ services/  │  └─────▶│   Temporal    │
                │ semantic   │         └───────┬───────┘
                │ (Cube)     │                 │
                └──────┬─────┘         ┌───────▼────────┐
                       │               │ services/worker│
                ┌──────▼───────┐       │  connectors,   │
                │  ClickHouse  │◀──────│  mapping, dbt, │
                │  analytics   │       │  detectors     │
                └──────────────┘       └───────┬────────┘
                                               │
                                       ┌───────▼────────┐
                                       │ S3 / MinIO raw │
                                       └────────────────┘
```

The web application never talks to ClickHouse, Cube, Temporal or object storage directly. One
inbound door: `services/api`. This is what makes tenant scoping testable in one place.

## 3. Request paths

**Read a gap list.** Browser → API (`GET /v1/gaps`, cursor paginated) → PostgreSQL with RLS →
response. No analytics query on this path; gap rows carry their denormalised display values so the
inbox stays fast. Target p95 < 750 ms.

**Read a metric.** Browser → API (`POST /v1/metrics/{key}/query`) → the API validates the metric key,
dimensions and filters against the certified definition, injects `organization_id`, then calls Cube
with a service token. Cube applies its own tenant policy as defence in depth and hits ClickHouse or
a pre-aggregation. Target p95 < 1 s.

**Ingest.** Schedule or webhook → Temporal workflow → connector activity (`dlt` behind the SDK) →
raw payload to object storage → staging → mapping version applied → canonical rows into ClickHouse →
dbt run → `fact_metric_observation` refreshed → detector workflow → gap created/updated.

**Detect.** Temporal scheduled workflow → detector reads governed metrics + canonical facts →
candidates → suppression → dedupe → correlation → gap upsert in PostgreSQL → audit events. Every run
writes a `detector_run` record with versions, query hash, window, thresholds, candidate counts,
suppressed counts, dedupe decisions, duration and errors.

**Progress.** Long-running connector and detector runs stream progress over Server-Sent Events from
the API, which subscribes to Temporal. The browser never polls Temporal.

## 4. Web application

Next.js App Router, current stable React, strict TypeScript, Tailwind with project tokens, Radix
primitives, Motion for React, TanStack Query, TanStack Table and Virtual, React Hook Form + Zod,
Visx with D3 scales, Storybook, Playwright, axe.

- Server Components for server-rendered read surfaces; client components for interaction-heavy
  tables, inspectors and charts.
- Filters, time windows, grouping and selected view live in the URL, not component state, so a view
  is shareable and the back button works.
- No large CSS strings in components — a lint rule fails the build on a `<style>` element containing
  more than 200 characters, which is exactly what the legacy prototype does today.
- No hard-coded metric values in UI files — a lint rule flags numeric literals with currency or
  percent formatting outside `packages/demo` and test fixtures.

## 5. API

FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, typed OpenAPI, RFC 9457 problem responses, cursor
pagination, idempotency keys on writes and ingest, ETags for concurrent edits, SSE for progress,
rate limiting, request and trace ids. Versioned under `/v1`. Resource groups per the brief.

The TypeScript client is generated from the OpenAPI document in CI and committed to
`packages/contracts`. A drift check fails the build if the committed client does not match the
served schema.

Product and control APIs stay in one service until measured load or team ownership justifies a
split. Splitting early would duplicate the tenant-scoping logic, which is the thing least safe to
duplicate.

## 6. Control plane — PostgreSQL

Organizations, memberships and roles, source definitions and connections, encrypted credential
references, connector runs and checkpoints, schema and mapping versions, metric metadata, detector
rules, gap lifecycle, actions, outcomes, comments, audit history, retention settings, demo snapshots.

Row-level security on every organization-scoped table, in addition to service-layer checks. The
application connects as a role that cannot bypass RLS, and the session sets
`app.current_organization_id` inside the transaction. Cross-tenant negative tests run in CI and are
a release gate.

Audit events are append-only: no UPDATE or DELETE grant on the audit table for the application role.

## 7. Analytics plane — ClickHouse

Canonical facts, dimensions, metric observations, detector inputs, aggregates. Physical design rules
are in [docs/data-contracts.md](data-contracts.md#clickhouse-physical-rules). See
[ADR 0002](adr/0002-analytics-store.md).

## 8. Raw storage

S3-compatible object storage for immutable raw payloads, uploads, connector response snapshots,
rejected records and Parquet exports. MinIO locally; S3 or R2 hosted, behind a storage adapter.
Object keys are content-addressed and versioning is enabled; the application role has no delete
permission — retention deletion runs under a separate credential. See
[ADR 0006](adr/0006-raw-storage.md).

## 9. Ingestion and orchestration

`dlt` for REST extraction, pagination, auth, incremental state, merge and schema handling, wrapped
behind the connector SDK so product code never imports a dlt type. Temporal for durable runs,
backfills, cleansing, detector runs, retries, schedules, cancellation and progress. See
[ADR 0003](adr/0003-workflow-engine.md).

Every external call has bounded retries, exponential backoff with jitter, rate-limit handling,
timeout, an idempotency strategy, checkpointing, structured errors and propagated trace context.
Partial failure of one resource does not roll back other resources that succeeded — the workflow
records per-resource outcomes.

## 10. Transformation and semantic layer

dbt Core with the ClickHouse adapter for canonical transformations, tests and documentation. Cube
Core as the governed semantic layer for measures, dimensions, joins, access policies,
pre-aggregations and serving. Only certified metrics and authorised dimensions are exposed to
product and AI consumers. See [ADR 0004](adr/0004-semantic-layer.md), which also records the
fallback if the dbt-ClickHouse-Cube combination proves unsafe in practice.

## 11. Auth

Better Auth owns identity, sessions, organizations, invitations and JWT issuance with JWKS; FastAPI
verifies tokens against JWKS and owns capability checks. An auth-provider boundary keeps enterprise
SSO (WorkOS) addable later without touching product permissions. Roles: `frontline`, `manager`,
`analyst`, `admin`, `owner`, `presenter-demo`. See [ADR 0005](adr/0005-auth-provider.md).

## 12. AI boundary

The AI layer receives a structured evidence bundle assembled by the API and semantic layer. It has
no database access, cannot produce numbers, and every answer cites internal metric, gap and evidence
identifiers the UI can open. The MCP server is read-first; writes are separate, permissioned,
confirmed tools. See [ADR 0007](adr/0007-ai-boundary.md).

## 13. Observability

OpenTelemetry traces, metrics and structured logs across web, API, worker, connector and detector
paths. Trace context propagates from a UI action through the API, the Temporal workflow, the
connector call, the transformation and the detector run. Spans carry organization and run
identifiers; never personal data or secrets, enforced by a redaction processor.

Local dashboards or documented exports for: API latency and error rate, connector run health,
records processed and rejected, workflow retries, ClickHouse query duration, detector duration and
output count, gap creation and dedupe rates, demo reset runs.

## 14. Infrastructure

Docker Compose for local, one command to start everything, production Dockerfiles, OpenTofu modules
or a provider-neutral deployment layer, separate local/preview/staging/production configuration,
migration jobs, backup and restore runbooks, health and readiness probes, zero-downtime-compatible
schema changes (expand–migrate–contract; no destructive migration in the same release as the code
that stops using a column).

Hosted reference: managed PostgreSQL, ClickHouse, object storage and Temporal, with portable service
containers. The Cloudflare Workers runtime the prototype uses is not a target for the platform —
see [ADR 0008](adr/0008-hosting-target-and-legacy-runtime.md).
