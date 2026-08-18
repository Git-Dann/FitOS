# CLAUDE.md

Durable instructions for this repository. Keep it short — project narrative belongs in `docs/`.

Read [docs/master-build-brief.md](docs/master-build-brief.md) and [docs/build-state.md](docs/build-state.md)
before starting a phase. Read only the ADRs and code that phase needs.

## Current state

Phases A and B are complete. The monorepo, the `uv` Python workspace, tenancy with PostgreSQL RLS,
capability-based authorisation, the Gap aggregate, invitations and Better Auth are in place, and
`pnpm verify` passes. Phase C (the data plane) has not started — the phase plan is in
[docs/implementation-plan.md](docs/implementation-plan.md), live status in
[docs/build-state.md](docs/build-state.md).

Every environment variable is documented in [docs/configuration.md](docs/configuration.md).
Migrations need `FITOS_APP_ROLE_PASSWORD` and `FITOS_AUTH_ROLE_PASSWORD`; neither has a default,
because a default here becomes a production credential.

Do not assume a command works because this file or a spec document mentions it. Commands not
yet implemented exit non-zero with an "added in Phase X" message; that is deliberate.

### Commands that work today

| Command | Notes |
| --- | --- |
| `pnpm install` · `uv sync --all-packages` | Both lockfiles are committed |
| `pnpm verify` | **The phase gate.** format, lint, typecheck, unit tests, token contrast, ruff, mypy, pytest |
| `pnpm build` | Turborepo build across the workspace |
| `pnpm dev` | web on :3000, api on :8000 |
| `pnpm dev:infra` | Compose up, waits for health. **Authored but never started — no Docker daemon was available when it was written.** Verify before relying on it |
| `pnpm test:tokens` | 31 contrast pairs across both themes |
| `uv run pytest services/api/tests` | 132 tests. Needs `FITOS_TEST_DATABASE_URL`; without it the tenancy suite **skips**, so set `FITOS_REQUIRE_DB_TESTS=1` to turn a skip into a failure |
| `pnpm lint:py` · `typecheck:py` · `test:unit:py` | ruff · mypy · pytest |

### Not yet implemented

`test:e2e` · `test:visual` (Phase E) · `test:data` (Phase D) · `demo:seed` · `demo:reset` ·
`demo:snapshot` · `demo:purge` · `demo:verify` (Phase F). Each exits non-zero rather than
succeeding silently.

### Legacy prototype

`legacy/fitos-prototype/` keeps the original Cloudflare-runtime prototype, outside the pnpm
workspace with its own lockfile ([ADR 0008](docs/adr/0008-hosting-target-and-legacy-runtime.md)).
Its `npm test` was broken from commit `0d530e2` until Phase A fixed the script wiring; it now
passes 3/3. Do not reformat this tree — it is preserved, not maintained.

## Architecture boundaries

- One inbound door: the browser talks to `apps/web`, which talks to `services/api`. The web app never
  reaches ClickHouse, Cube, Temporal or object storage directly.
- Product code never imports a `dlt` type. Connectors go through `connectors/sdk`.
- Detectors read canonical facts and governed metrics. Product UI reads governed metrics only. No
  application code reads the raw or staging layers.
- Connectors never construct their own HTTP client — they use the one on `ConnectorContext`, which
  carries the egress policy, rate limiter and trace context.
- Temporal workflow bodies are deterministic: no wall-clock time, no randomness, no I/O. Put those in
  activities.

## Non-negotiable rules

- **Tenant scoping.** `organization_id` comes from the verified token, never from a request body,
  query string, header or cookie. Every org-scoped table has RLS. Every new endpoint gets a
  cross-tenant negative test in the same commit.
- **Capabilities, not roles.** `can("gap.assign")`, never `role === "manager"`.
- **No hard-coded metrics.** No analytical value, formula or currency literal in a React component.
  Metrics come from the governed layer. Formulas exist once.
- **No gap without** a metric version, detector version, evidence and an as-of time.
- **No modelled money without** low, base, high, assumptions and confidence.
- **No AI-produced number** is ever a metric result. AI cites; it does not calculate.
- **No secrets** in application tables, logs, errors, traces or API responses. Never write to `.env`
  or secret files.
- **No silent failure.** Rejected records are quarantined with a reason and counted. Schema drift is
  surfaced. A partial result says it is partial.
- **No causal claim** from correlation. Only a `controlled_test` outcome may use causal language.
- **No fake status.** A connector card shows its real state; `fixture` is never dressed as `healthy`.
- **No placeholder buttons** on a route marked complete.
- **No guard without a test that it fails.** A coverage check that finds nothing passes
  everything, and looks exactly like one that works. Phase B shipped a cross-tenant route guard
  that silently checked nothing for a whole phase.

## Destructive commands

- Demo seed, reset, snapshot, purge and verify are the only sanctioned data-destructive path.
- Purge requires the exact tenant slug and a tenant flagged `is_demo`. Never target all
  organizations. Every run, including a refusal, writes an audit record. Every command supports
  `--dry-run`.
- Never run a destructive database command outside this path. Migrations are
  expand–migrate–contract; no destructive migration ships in the same release as the code that stops
  using the column.

## Verification

Do not claim success from reading code. Show command output, test results, record counts, API
responses or screenshots.

Before marking a UI route complete: capture screenshots at 1440 × 900, 1024 × 768 and 390 × 844,
have the design-reviewer subagent compare them against [docs/design-system.md](docs/design-system.md),
and fix the findings. Test empty, loading, delayed, partial, error, unauthorised and offline-recovery
states — a passing happy path is not completion.

## Commits

- Imperative subject under 72 characters, e.g. `Add connector SDK contract tests`.
- One coherent outcome per commit; keep the branch buildable.
- Never commit secrets, `.env` files, or the model identifier of the assistant that wrote the code.

## Session protocol

Fresh session per phase. End every session by updating `docs/build-state.md`, running the phase
checks, committing, and printing the exact prompt for the next session. Never mark a phase complete
while its acceptance checks fail.
