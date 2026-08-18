# ADR 0008 — Hosting target and the legacy runtime

Status: accepted · Date: 2026-08-14 · Phase: A

This ADR is not in the brief's list. It exists because the audit found a conflict the brief could not
have known about, and leaving it unrecorded would make Phase A ambiguous.

## Context

The brief specifies FastAPI, Temporal, ClickHouse, MinIO, dbt and Docker Compose, with managed
PostgreSQL, ClickHouse, object storage and Temporal as the hosted reference.

The repository as it stands targets **Cloudflare Workers**: `vinext` 0.0.50, `@cloudflare/vite-plugin`,
`worker/index.ts`, D1 and R2 bindings in `.openai/hosting.json`, and Drizzle configured for SQLite.
A second, partly conflicting target was added later — commit `0d530e2` switched `build` to
`next build` for Vercel, which is also what broke `npm test`
(see [docs/repo-audit.md](../repo-audit.md#verified-regression-npm-test-is-broken)).

None of the required platform services can run on Workers. Workers has no long-lived processes for
Temporal workers, no Python runtime for FastAPI, connectors and detectors, and no path to ClickHouse
or dbt. This is not a refactor; it is a different platform.

## Decision

**The platform targets containers, not Cloudflare Workers.** `apps/web` runs as a Node server
(Next.js standalone output) in a container. Python services run in containers. Local development is
Docker Compose. Hosted deployment is provider-neutral, described in OpenTofu modules, with managed
PostgreSQL, ClickHouse, object storage and Temporal.

**The prototype is preserved, not ported.** `legacy/fitos-prototype/` keeps the Cloudflare runtime
intact and buildable, with its own lockfile, excluded from the pnpm workspace. It remains the
demonstrable artefact until Phase F, and remains a reference afterwards.

**Object storage keeps a Cloudflare option.** R2 is S3-compatible, so the storage adapter in
[ADR 0006](0006-raw-storage.md) supports it. That is the one piece of the Cloudflare stack that
survives on merit rather than inertia.

## Alternatives considered

**Keep Workers for the web tier and containers for everything else.** Preserves the existing deploy
path and Workers' edge characteristics. Rejected: two deployment models, two build systems and two
sets of runtime constraints for one application, in exchange for edge latency on an internal
operational tool whose users are authenticated staff. The cost is ongoing; the benefit is negligible
here.

**Port the platform to Workers-compatible technology** (D1 instead of PostgreSQL, Workflows instead
of Temporal, no Python). Rejected: it would abandon RLS, dbt, Cube, `dlt` and the entire Python
connector and detector stack — effectively rewriting the brief around a runtime constraint rather
than a product requirement.

**Delete the prototype.** Rejected: it is currently the only demonstrable asset, and its
`design-qa.md`, screenshots and fulfilment rules are genuine work product.

## Consequences

- `worker/index.ts`, `db/`, `examples/d1/`, `app/chatgpt-auth.ts`, `.openai/hosting.json`,
  `vite.config.ts` and `drizzle.config.ts` move into `legacy/` rather than being adapted. None is
  FitOS code — all are starter scaffolding.
- The Vercel-oriented `next build` script and the vinext build stop competing, because the legacy
  tree owns both and the platform's `apps/web` has its own. Fixing that script wiring so the legacy
  tests pass again is a Phase A acceptance item.
- The legacy tree's 16 high-severity transitive advisories are quarantined behind its own lockfile
  and are not in the platform's dependency graph. They are still reported, and the legacy tree is
  excluded from the CI audit gate with a recorded, dated exception rather than silently ignored.
- If Cloudflare hosting is later required for the web tier specifically, it returns as a new ADR with
  a measured case — not as an assumption inherited from a starter template.
