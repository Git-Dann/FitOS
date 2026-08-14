# CLAUDE.md

Durable instructions for this repository. Keep it short — project narrative belongs in `docs/`.

Read [docs/master-build-brief.md](docs/master-build-brief.md) and [docs/build-state.md](docs/build-state.md)
before starting a phase. Read only the ADRs and code that phase needs.

## Current state

The monorepo does not exist yet. As of Session 1 this is still the single-package prototype, and
only the commands in the "today" table below work. Do not assume a command exists because this file
or a spec document mentions it.

### Commands that work today

| Command | Notes |
| --- | --- |
| `npm ci` | |
| `npm run lint` | Clean |
| `npx tsc --noEmit` | Clean |
| `npm run test:rules` | 5 tests, pass |
| `npm run build:vinext` | Produces `dist/` |
| `npm test` | **Broken.** Runs `next build`, which does not produce the `dist/` the test imports. Run `npm run build:vinext && node --test tests/rendered-html.test.mjs` instead. Fixed in Phase A. |

### Target commands (Phase A onward)

`pnpm install` · `dev` · `dev:infra` · `build` · `lint` · `typecheck` · `test` · `test:unit` ·
`test:integration` · `test:e2e` · `test:visual` · `test:data` · `verify` · `demo:seed` ·
`demo:reset` · `demo:purge` · `demo:verify`

`pnpm verify` is the gate before claiming a phase complete.

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
