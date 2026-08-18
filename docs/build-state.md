# Build state

Updated at the end of every session. Read this before starting a phase.

---

## current_phase

Phase A — repository and local platform.

## status

**Complete, with three acceptance items that could not be verified in this environment.**
Everything else was verified by execution. The exceptions are named in
[open_risks](#open_risks) and repeated here rather than buried: this container has no
Docker daemon and no CI runner, so Compose was authored and syntax-checked but never
started, the container footprint measurement has not been taken, and the CI workflow has
never executed.

Session 1 (audit and specification) is complete and unchanged — see
[session history](#session-history).

## completed_outcomes

1. **Prototype preserved with history intact.** `git mv` into `legacy/fitos-prototype/`;
   `git log --follow` traces `fulfilment-engine.ts` back to its creation commit `5009b01`.
   The four design-QA screenshots moved to `docs/screenshots/legacy/`.
2. **The Session 1 regression is fixed.** `legacy/fitos-prototype` `npm test` now runs
   `build:vinext` and passes 3/3. It had failed on every commit since `0d530e2` (31 Jul).
3. **pnpm + Turborepo workspace** with `apps/web` and `packages/{config,contracts,ui}`;
   `uv` workspace with `services/{api,worker}`. Both lockfiles committed.
4. **Legacy is outside the workspace** with its own lockfile, so its 16 high-severity
   Cloudflare-toolchain advisories are not in the platform dependency graph
   ([ADR 0008](adr/0008-hosting-target-and-legacy-runtime.md)).
5. **Health and readiness probes that mean something.** `/ready` returns 503 when a
   dependency is down, names which one, and reports the exception _type_ only — a test
   asserts a DSN with an embedded password never reaches the response body.
6. **The colour system is now code, not documentation.** `packages/ui` generates
   `tokens.css` from `docs/design-tokens/tokens.json`; five tests assert the generated
   CSS, including that no white-on-orange label can appear in either theme.
7. **Docker Compose** for PostgreSQL, ClickHouse, MinIO, Temporal (+UI) and Cube, with
   pinned versions and healthchecks, behind `pnpm dev:infra`, which waits for health.
8. **CI skeleton** with six jobs. Visual regression is declared and _skipped_, not stubbed
   green, because no baselines exist before Phase E ([spec-review](spec-review.md) T2).
9. **README rewritten** for the monorepo — it was still the vinext starter README.

## changed_files

```text
root            package.json · pnpm-workspace.yaml · turbo.json · pyproject.toml
                .prettierrc.json · .prettierignore · .gitignore · README.md
                pnpm-lock.yaml · uv.lock
apps/web        Next.js app, /health route, token-based globals.css
packages/       config (shared tsconfig) · contracts (health types + tests)
                ui (token generator + 5 tests)
services/       api (FastAPI, health + readiness registry, 5 tests)
                worker (package scaffold, 1 test) · semantic (Cube conf mount)
infra/          compose/docker-compose.yml · scripts/dev-infra.sh
.github/        workflows/ci.yml
legacy/         entire prototype, moved with history; test script fixed
docs/           screenshots/legacy/ (4 PNGs moved from the repository root)
```

## commands_run

All at `/home/user/FitOS` on `claude/md-file-review-67empl`. Node 22.22.2, pnpm 10.33.0,
uv 0.8.17, Python 3.11.15.

| Command                                          | Result                                                                 |
| ------------------------------------------------ | ---------------------------------------------------------------------- |
| `pnpm verify`                                    | **exit 0** — format, lint, typecheck, unit, tokens, ruff, mypy, pytest |
| `pnpm build`                                     | **exit 0** — 2 tasks, web compiled, 3 routes                           |
| `pnpm test:tokens`                               | **31 pairs, 0 failing**                                                |
| `pnpm --filter @fitos/ui test:unit`              | 5 pass, 0 fail                                                         |
| `pnpm --filter @fitos/contracts test:unit`       | 2 pass, 0 fail                                                         |
| `uv run pytest -q`                               | 6 passed                                                               |
| `uv run mypy services`                           | Success: no issues found in 6 source files                             |
| `uv run ruff check services`                     | All checks passed                                                      |
| legacy: `npm run test:rules`                     | 5 pass, 0 fail                                                         |
| legacy: `npm test`                               | **3 pass, 0 fail** — was 1/3 before this phase                         |
| `curl :8000/health`                              | `{"status":"ok","service":"api","version":"0.0.0"}` HTTP 200           |
| `curl :8000/ready`                               | `{"status":"ready","service":"api","checks":{}}` HTTP 200              |
| `curl :3000/health`                              | `{"status":"ok","service":"web","version":"0.0.0"}` HTTP 200           |
| `git log --follow legacy/…/fulfilment-engine.ts` | resolves to `5009b01 Build adaptive fulfilment rules`                  |
| `bash infra/scripts/dev-infra.sh up`             | exits 1, "the Docker daemon is not running" — clean refusal            |
| `yaml.safe_load(docker-compose.yml)`             | valid; 7 services, 4 volumes                                           |
| `yaml.safe_load(ci.yml)`                         | valid; 6 jobs                                                          |

## test_results

19 automated tests across three suites, all passing: 6 Python (api 5, worker 1),
7 JavaScript (ui 5, contracts 2), 8 legacy (rules 5, render 3). Plus 31 token contrast
pairs.

The tests worth naming, because each encodes a rule rather than exercising a code path:

- `test_a_raising_probe_never_leaks_its_message` — a probe raising
  `ConnectionError("postgres://fitos:hunter2@db.internal:5432/…")` yields
  `detail: "ConnectionError"`, and the response body contains neither the password nor
  the host ([threat-model](threat-model.md) T3).
- `the label on an accent fill is near-black in both themes` — asserts `--on-accent` is
  `#0B0C0E` in both themes and that `#FFFFFF` never appears as an on-accent value. White
  on orange measures 3.90:1 and fails AA.
- `every semantic reference resolved to a literal colour` — catches an unresolvable token
  reference at build time rather than as a browser rendering a literal string.

## decisions_and_adrs

No new ADRs. Phase A implements the decisions recorded in Session 1. Three implementation
choices worth recording:

1. **Application services run on the host, not in Compose.** Compose provides
   infrastructure only, so a code change does not require an image rebuild. Production
   Dockerfiles arrive in Phase I.
2. **Prettier does not format `docs/` or `legacy/`.** It pads markdown tables to align
   columns, which produced a 20-file diff on hand-edited prose the first time it ran, and
   reformatting the frozen legacy tree defeats the point of freezing it. Code formatting is
   enforced; prose formatting is not.
3. **Unimplemented commands exit non-zero** with an "added in Phase X" message rather than
   succeeding silently. A command that quietly does nothing is how a phase gets marked
   complete without being complete.

## open_risks

| #   | Risk                                                                    | Status                                                                                                                                                                              |
| --- | ----------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **Compose is unverified.** No Docker daemon in this environment          | **Open, blocking for Phase C.** The file is syntax-valid and versions are pinned, but no container has been started. First task of the next session on a Docker-capable machine.     |
| 2   | **Compose footprint unmeasured** — the Phase A item that feeds risk 3    | **Open.** `pnpm dev:infra footprint` exists to take the measurement; it has never run. Must be taken before the ≈1.42M-record dataset lands in Phase F.                              |
| 3   | Five infra containers plus ≈1.42M records versus p95 targets on a laptop | Unchanged from Session 1. Cannot be assessed until risk 2 is closed.                                                                                                                |
| 4   | 16 high-severity advisories in the legacy Cloudflare toolchain           | **Contained.** Outside the workspace with its own lockfile; CI reports them through a non-gating job with a recorded exception rather than hiding them.                              |
| 5   | Cube × ClickHouse × dbt-clickhouse compatibility                         | Versions now pinned in Compose. Untested until risk 1 is closed.                                                                                                                    |
| 6   | Better Auth is young for a security-critical position                    | Unchanged. Provider boundary in [ADR 0005](adr/0005-auth-provider.md).                                                                                                              |
| 7   | **CI has never executed**                                                | **Open.** The workflow is syntax-valid but this repository has no Actions history, so the first push with the workflow present is its first real run.                                |

Risks 1, 2 and 7 share one cause: this environment has no Docker daemon and no CI runner.
None is a defect in the work; all three are unverified claims, and they are listed as
unverified rather than assumed good.

## next_phase

**Phase B — auth and tenancy.** Acceptance criteria in
[implementation-plan.md](implementation-plan.md#phase-b--auth-and-tenancy).

Close the three open verification items first. They are cheap on a Docker-capable machine
and they gate Phase C regardless.

## next_session_prompt

```text
Read @docs/master-build-brief.md, @docs/build-state.md, @docs/implementation-plan.md,
@CLAUDE.md and @docs/adr/0005-auth-provider.md. Start in Plan Mode.

First close the three Phase A verification gaps, which need a Docker-capable machine:
run `pnpm dev:infra` and confirm every container reaches healthy; run
`pnpm dev:infra footprint` and record container memory and startup time in
docs/build-state.md; confirm CI is green on the branch. If a container fails to start, fix
Compose before proceeding — Phase C depends on all of it.

Then implement Phase B end to end: organizations, memberships, roles and capabilities;
Better Auth with JWT/JWKS issuance and FastAPI verification against JWKS; PostgreSQL RLS
on every org-scoped table with the application role unable to bypass it; the append-only
audit base; the invitation flow; demo identities behind a production guard that fails
startup if enabled in production.

Cross-tenant negative tests are the release gate: for every endpoint, org A's token must
not read, update or delete org B's records, and must receive 404 rather than 403. Include
a test that RLS alone blocks the query with the service-layer filter deliberately removed,
proving defence in depth is real rather than assumed. Add a lint rule that fails on any
role-name comparison in application code.

Run pnpm verify, ask the verification-engineer subagent to challenge the result, fix its
findings, update docs/build-state.md, commit the coherent outcome and print the exact
prompt for the next fresh session. Do not start Phase C until Phase B passes its
acceptance checks.
```

## session history

| Session | Phase                       | Outcome                                                                                                                                                          |
| ------- | --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1       | Audit and specification     | 37 files: audit, 11 specification documents, 8 ADRs, contradiction review (14 items), Claude Code configuration. Verified regression found in `npm test`.         |
| 1b      | Palette                     | Near-black + orange, dark default, 31 contrast pairs measured rather than asserted. Both open questions closed by the repository owner.                           |
| 2       | A — repository and platform | Monorepo, legacy preserved with history, health probes, tokens as code, Compose, CI skeleton. `pnpm verify` exit 0. Three items unverified for lack of a daemon.  |
