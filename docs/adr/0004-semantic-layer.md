# ADR 0004 — Semantic layer

Status: accepted, with a defined fallback · Date: 2026-08-14 · Phase: D

## Context

A non-negotiable product rule is that a metric formula exists once and serves the UI, exports, API
and AI tools. The legacy prototype violates this comprehensively: `£1.1k` and `71%` are literals in
JSX with no definition behind them. The replacement must make the violation structurally impossible,
and must carry tenant policies and dimension allowlists so the AI layer cannot query beyond what a
caller may see.

## Decision

dbt Core with the ClickHouse adapter for canonical transformations, tests and documentation. Cube
Core as the governed semantic layer for measures, dimensions, joins, access policies,
pre-aggregations and serving. Only certified metrics and authorised dimensions are exposed to
product and AI consumers.

The metric contract in [docs/data-contracts.md](../data-contracts.md#5-governed-metric-contract) is
the human-authored source; Cube models and dbt tests are generated or validated against it, so a
definition cannot drift from its contract without failing CI.

## Alternatives considered

**dbt metrics / MetricFlow.** Keeps everything in one tool. Rejected: weaker multi-tenant access
policies and no serving API of the kind the product and MCP layer need, so the tenant policy would
have to be reimplemented in the API — the exact duplication this ADR exists to prevent.

**A hand-rolled metric service.** Full control, no adapter compatibility risk, and honestly viable
for nineteen metrics. Rejected because pre-aggregation, join-path resolution and dimension
allowlisting are where the real work is, and rebuilding them is a distraction from the gap engine.
Kept as the fallback below.

**Serving ClickHouse views directly.** Rejected: no access policy layer, and the metric definition
ends up spread across SQL files with no contract.

## Fallback, pre-authorised

The brief anticipates that the dbt-ClickHouse-Cube combination may hit a compatibility problem. If
Phase D finds one that cannot be resolved safely:

1. Record the failure with benchmarks and a reproduction in a superseding ADR.
2. Keep dbt Core for transformations and tests — it is the lower-risk half.
3. Replace Cube with the smallest thing that keeps metric definitions governed and reusable: a thin
   Python metric service inside `services/api` that compiles the same YAML contract into parameterised
   ClickHouse SQL, applies the tenant filter and the dimension allowlist, and caches aggregates in
   ClickHouse tables rather than a bespoke cache.

The metric contract does not change under the fallback. That is deliberate: the contract is the
asset, and the serving engine is an implementation detail. This is what makes the fallback cheap.

## Consequences

- Cube adds a service to Compose and a version-compatibility matrix (Cube × ClickHouse adapter ×
  dbt-clickhouse) that must be pinned and tested, not floated.
- Metric changes touch three artefacts (contract, Cube model, dbt test). Generation from the contract
  keeps them consistent; a drift check in CI is required, not optional.
- Pre-aggregations improve p95 but add staleness. Every served metric carries its as-of time so a
  pre-aggregated value can never be mistaken for live.
- The AI layer queries Cube through the API, never directly, so tenant policy is applied twice.
