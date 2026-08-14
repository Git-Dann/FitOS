# ADR 0001 — Monorepo structure and package managers

Status: accepted · Date: 2026-08-14 · Phase: A

## Context

The repository is a single npm package (`site-creator-vinext-starter`) containing a Next.js
prototype. The target platform has two language ecosystems and at least twelve deployable or
publishable units: a web app, a Storybook, three Python services, six shared packages, ten
connectors, a dbt project and infrastructure.

## Decision

A single repository with pnpm workspaces and Turborepo for JavaScript/TypeScript, and `uv` with a
locked dependency file for Python, using the layout in
[docs/architecture.md](../architecture.md#1-repository-layout). Both lockfiles are committed.

The legacy prototype is preserved under `legacy/fitos-prototype/` with its **own** lockfile and is
excluded from the workspace, so its dependency graph does not enter the platform's.

## Alternatives considered

**Keep npm workspaces.** Cheapest migration — the lockfile survives. Rejected: the brief specifies
pnpm, and pnpm's strict node_modules layout catches phantom dependencies, which matters when
`packages/ui` must not accidentally resolve a transitive dependency of `apps/web`.

**Nx instead of Turborepo.** Stronger generators and dependency graph analysis. Rejected as heavier
than needed; Turborepo's task graph and remote caching cover the requirement, and the brief names it.

**Polyrepo.** Independent versioning per service. Rejected: contracts are generated from the API
schema into the web client, and detector fixtures are shared between Python and TypeScript. A
polyrepo makes every contract change a multi-repo dance, which at this stage is pure cost.

**Poetry or pip-tools for Python.** Rejected: `uv` is materially faster in CI, produces a
cross-platform lock, and the brief names it.

## Consequences

- The committed `package-lock.json` is replaced. The legacy tree keeps its own so the prototype
  stays buildable and reproducible during the migration.
- CI needs both toolchains and both caches.
- Turborepo task definitions become the source of truth for `pnpm verify`, so a new package is only
  covered by CI once it declares its tasks — a gap worth watching in review.
- `git mv` preserves history for the moved prototype; `git log --follow` is an acceptance check in
  Phase A.
