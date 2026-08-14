# Build state

Updated at the end of every session. Read this before starting a phase.

---

## current_phase

Session 1 — audit and specification. No platform code.

## status

**Complete.** Planning only. Planning is not completion of the project; Phase A has not started.

## completed_outcomes

1. Repository audited against the running code, not only by reading it. Findings in
   [repo-audit.md](repo-audit.md), including a verified regression: `npm test` has been broken since
   commit `0d530e2` (31 Jul 2026).
2. Master build contract saved verbatim to [master-build-brief.md](master-build-brief.md).
3. Specification set written: product spec, gap model, data contracts, architecture, design concepts,
   design system, connector SDK, security and privacy, threat model, demo plan, implementation plan.
4. Eight ADRs, including one the brief did not anticipate (0008) resolving the Cloudflare Workers
   versus container-platform conflict the audit surfaced.
5. Specification reviewed for contradictions: [spec-review.md](spec-review.md) — 14 items, 8 resolved,
   4 tensions to measure, 2 open questions for the user.
6. Three design concepts scored and combined, with the working shown. Concept A wins the shell,
   C takes gap detail, B is bounded to the manager view.
7. Claude Code configuration: `CLAUDE.md`, 5 subagents, 4 skills, 4 hooks with `settings.json`.
   Hooks tested against real payloads, including false-positive checks.

## changed_files

37 new files, no existing file modified.

```text
CLAUDE.md
docs/  master-build-brief · repo-audit · product-spec · gap-model · data-contracts · architecture
       design-concepts · design-system · connector-sdk · security-and-privacy · threat-model
       demo-plan · implementation-plan · spec-review · build-state
docs/adr/  0001 monorepo · 0002 analytics store · 0003 workflow engine · 0004 semantic layer
           0005 auth provider · 0006 raw storage · 0007 AI boundary · 0008 hosting target
.claude/  settings.json · agents/×5 · skills/×4 · hooks/×4
```

## commands_run

Run at `/home/user/FitOS`, branch `claude/md-file-review-67empl`, base commit `439a0df`,
Node 22, npm 10.9.7.

| Command | Result |
| --- | --- |
| `npm ci` | 601 packages; 21 vulnerabilities (1 low, 4 moderate, 16 high) |
| `npm run test:rules` | **5 pass, 0 fail** |
| `npm run lint` | clean, no output |
| `npx tsc --noEmit` | clean, no output |
| `npm test` | **1 pass, 2 fail** — `ERR_MODULE_NOT_FOUND: dist/server/index.js` |
| `npm run build:vinext` | build complete, `dist/server/index.js` produced |
| `node --test tests/rendered-html.test.mjs` (after `build:vinext`) | **3 pass, 0 fail** |
| `npm audit` | 21 advisories, near-all transitive via wrangler/miniflare/ws/sharp/esbuild-kit |
| Hook payload tests | secret-write block ✓, `.env.example` allowed ✓, DROP/TRUNCATE/unbounded DELETE-UPDATE blocked ✓, `demo:*` allowed ✓, `grep truncate` and `rm -rf ./dist` not false-positived ✓, `rm -rf /` blocked ✓ |

## test_results

Existing test suites are genuinely healthy; the repository's headline command is not.

- `tests/fulfilment.test.ts` — 5/5 pass. These become detector golden fixtures in Phase D.
- `tests/rendered-html.test.mjs` — 3/3 pass **when built with `build:vinext`**, 1/3 via `npm test`.
- Root cause: commit `0d530e2` switched `build` to `next build` (Vercel) while `test` still depends
  on the vinext `dist/` output. Script wiring, not code. Fixed in Phase A.

## decisions_and_adrs

| ADR | Decision |
| --- | --- |
| [0001](adr/0001-monorepo-and-package-manager.md) | pnpm + Turborepo; `uv` for Python; legacy tree outside the workspace with its own lockfile |
| [0002](adr/0002-analytics-store.md) | ClickHouse for analytics, PostgreSQL for the control plane |
| [0003](adr/0003-workflow-engine.md) | Temporal for durable runs; `dlt` behind the connector SDK |
| [0004](adr/0004-semantic-layer.md) | dbt Core + Cube Core, with a pre-authorised fallback that keeps the metric contract unchanged |
| [0005](adr/0005-auth-provider.md) | Better Auth owns identity; FastAPI owns capability-based authorisation |
| [0006](adr/0006-raw-storage.md) | S3-compatible immutable raw storage; app role has no delete permission |
| [0007](adr/0007-ai-boundary.md) | AI cites, never calculates; read-first MCP; answers rejected on unresolvable citations |
| [0008](adr/0008-hosting-target-and-legacy-runtime.md) | Containers, not Cloudflare Workers; prototype preserved intact in `legacy/` |

Design decision: Concept A (Gap Ledger) is the shell and `/inbox`; Concept C (Evidence Workbench) is
gap detail and `/explore`; Concept B (Operations Radar) is one component on `/manager` and the
opening beat of the presenter flow. Scored 70 / 59 / 46; ranking is unchanged if implementation risk
is removed from the table.

## open_risks

| # | Risk | Mitigation |
| --- | --- | --- |
| 1 | Five infra containers plus ≈1.42 M records versus p95 targets on a laptop | Measure container footprint in Phase A **before** the dataset exists; benchmark with query plans in Phase D. If missed, reduce the default seed or document minimum hardware — do not relax the targets quietly |
| 2 | 16 high-severity advisories in the legacy Cloudflare toolchain | Quarantined behind the legacy lockfile, outside the workspace, excluded from the audit gate with a dated recorded exception |
| 3 | Cube × ClickHouse × dbt-clickhouse version compatibility | Pin the matrix; fallback pre-authorised in ADR 0004 and costs nothing because the metric contract is unchanged |
| 4 | Better Auth is young for a security-critical position | Provider boundary in ADR 0005; JWKS contract tests for expiry, rotation, skew, algorithm confusion |
| 5 | Losing the only demonstrable asset mid-rewrite | Legacy prototype stays runnable until Phase F; vertical-slice-first sequencing |
| 6 | Vercel deployment at `fitos-retail-operations.vercel.app` may break when the prototype moves | Open question Q1; Phase A assumes it is live and records the exact setting change |

## next_phase

**Phase A — repository and local platform.** Acceptance criteria in
[implementation-plan.md](implementation-plan.md#phase-a--repository-and-local-platform).

Two things in Phase A are not cosmetic and should not be deferred: fixing the broken test-script
wiring, and measuring the Compose footprint on a normal machine. Both feed decisions later.

## next_session_prompt

```text
Read @docs/master-build-brief.md, @docs/build-state.md, @docs/implementation-plan.md, @CLAUDE.md,
@docs/adr/0001-monorepo-and-package-manager.md and @docs/adr/0008-hosting-target-and-legacy-runtime.md.
Start in Plan Mode. Confirm the bounded Phase A outcome, inspect only the related code, then
implement Phase A end to end: create the pnpm + Turborepo monorepo with uv for Python; git mv the
existing prototype into legacy/fitos-prototype/ preserving history and fix its broken test script so
its 5 rule tests and 3 render tests pass; move the four root design-qa PNGs into
docs/screenshots/legacy/; scaffold apps/web, services/api, services/worker and packages/*; add Docker
Compose for PostgreSQL, ClickHouse, MinIO, Temporal and Cube with one-command startup; add the root
command set including pnpm verify; add health and readiness probes; add the CI skeleton with the
visual-regression job declared pending rather than passing vacuously. Measure and record the Compose
memory footprint and startup time. Run the required tests, ask the verification-engineer subagent to
challenge the result, fix its findings, update docs/build-state.md, commit the coherent outcome and
print the exact prompt for the next fresh session. Do not start Phase B until Phase A passes its
acceptance checks.
```

## open questions for the user

Neither blocks Phase A; both change work in Phase A or F. Detail in
[spec-review.md](spec-review.md#open-questions-for-the-user).

1. Is the Vercel deployment live and being shown to anyone?
2. Is the prototype's green/off-white palette the fixed FitOS brand, or was it provisional?
