# Implementation plan

Nine bounded phases. Each runs in a fresh named Claude Code session, ends with passing acceptance
checks, a coherent commit and an updated [docs/build-state.md](build-state.md). A phase is never
marked complete while its acceptance checks fail.

Session 1 (this one) is planning: audit, specification set, ADRs, contradiction review, build state.
It produces no platform code. Planning is not completion.

## Sequencing principle

Build **one complete vertical slice before broad coverage**. The slice is the Stock Truth Gap
(Scenario 2), because it carries the strongest concepts from the existing prototype — ordinal stock
confidence, unmet demand as a record, alternatives partly accepted.

```text
seed → raw object → ingest → map → canonical fact → governed metric
     → gap → evidence → action → outcome → reset
```

Phases A–D build the slice's machinery; the slice itself completes at the end of D and is
demonstrable through the API before any product UX exists. Do not build five empty sections before
one section works end to end.

The legacy prototype stays runnable from `legacy/fitos-prototype/` until Phase F replaces it, so the
repository always has something demonstrable.

---

## Phase A — repository and local platform

**Outcome.** A monorepo that starts from one command, with the legacy prototype preserved and CI
running.

Work: create the pnpm + Turborepo workspace; `git mv` the prototype into `legacy/fitos-prototype/`
preserving history; move the four root PNGs into `docs/screenshots/legacy/`; scaffold `apps/web`,
`services/api`, `services/worker`, `packages/*`; add `uv` with a locked file; Docker Compose for
PostgreSQL, ClickHouse, MinIO, Temporal and Cube; one-command startup; root command set; health and
readiness probes; CI skeleton (format, lint, typecheck both ecosystems, unit tests, dependency
audit, secret scan).

**Acceptance**

- `pnpm install && pnpm dev:infra && pnpm dev` starts the stack from a clean clone.
- `pnpm lint`, `pnpm typecheck`, `pnpm test:unit` pass; `pnpm verify` runs them in order.
- Every service answers `/health` and `/ready`.
- The legacy prototype still builds and its 5 rule tests plus 3 render tests pass from
  `legacy/fitos-prototype/` — **fixing the broken `test` script wiring** identified in
  [docs/repo-audit.md](repo-audit.md#verified-regression-npm-test-is-broken).
- `git log --follow` resolves history for moved files.
- CI is green on the branch.

**Risks.** The pnpm migration invalidates the only lockfile in the repository. The legacy prototype's
Cloudflare toolchain carries 16 high-severity advisories; isolating it in `legacy/` with its own
lockfile keeps them out of the platform dependency graph — see
[ADR 0008](adr/0008-hosting-target-and-legacy-runtime.md).

---

## Phase B — auth and tenancy

**Outcome.** Nothing in the platform can be read or written without a verified organization context.

Work: organizations, memberships, roles and capabilities; Better Auth with JWT/JWKS; FastAPI token
verification and capability checks; PostgreSQL RLS on every org-scoped table; the append-only audit
base; invitation flow; demo identities behind a production guard.

**Acceptance**

- Cross-tenant negative tests pass for every implemented endpoint: org A cannot read, update or
  delete org B's records, receiving 404 rather than 403.
- RLS blocks the query even with the service-layer filter deliberately removed (a test that proves
  defence in depth is real).
- Capability checks are used everywhere; a lint rule fails on any role-name comparison in
  application code.
- Audit rows exist for every state transition; UPDATE and DELETE on the audit table fail as the
  application role.
- Startup fails if demo auth is enabled in production mode.

---

## Phase C — data plane

**Outcome.** A source record travels from upload or API to a canonical fact, with quarantine and
lineage, durably and idempotently.

Work: raw object storage with immutability; the connector SDK; CSV/XLSX upload and generic REST
connectors; Temporal workflows for runs, backfills and retries; the mapping and cleansing workspace
with versioning, preview and rollback; quarantine; canonical ClickHouse models; dbt project and
tests; egress controls; upload validation.

**Acceptance**

- The 14-point connector contract suite passes for both implemented connectors.
- Idempotency: the same extract run twice yields the same canonical row count.
- Duplicate webhook: the same signed delivery twice yields one canonical fact.
- SSRF: private, loopback, link-local and redirect-to-private targets are all refused.
- A mapping version can be created, previewed, backfilled, compared and rolled back through the API.
- A malformed record is quarantined with its reason and mapping version, and the run still completes;
  rejected counts are reported, never silent.
- dbt tests pass; canonical contract tests pass.
- Worker restart mid-backfill resumes from checkpoint without duplicating rows.
- Threat-model review for the ingestion boundary is recorded.

---

## Phase D — semantic and gap engine — *vertical slice completes here*

**Outcome.** The Stock Truth Gap exists end to end, from seeded records to an assigned action and a
recorded outcome, provable through the API.

Work: governed metric definitions as code; Cube models and tenant policies; the detector framework
with versioned config, typed I/O, replay and fixtures; the twelve detector classes (source mismatch
and ratio threshold first); exposure and confidence models; gap lifecycle with permissioned
transitions; evidence lineage; dedupe and correlation; actions and outcomes.

**Acceptance**

- A certified metric returns the same value through Cube, the API and a dbt test — one definition,
  three consumers.
- Metric golden tests pass; the `examples` block in each definition executes.
- Detector golden fixtures pass, including the five behavioural cases ported from the legacy
  `fulfilment-engine` tests, with the accessibility-override case intact.
- Scenario 2 produces **one** evolving stock-truth gap with a timeline across six days, not one per
  day — the dedupe release gate.
- Every created gap satisfies the aggregate invariants in [docs/gap-model.md](gap-model.md#invariants);
  a property test asserts no gap can be written without metric version, detector version, evidence
  and as-of time, and no exposure without low/base/high, assumptions and confidence.
- A gap can be assigned, actioned and resolved with an outcome through the API, with audit rows.
- A detector run record captures versions, query hash, window, thresholds, candidates, suppressions,
  dedupe decisions, duration and errors.
- Exposure fields are absent from a `frontline` token's payload.

---

## Phase E — product UX

**Outcome.** The ledger is usable by keyboard, dense, accessible and screenshot-reviewed.

Work: the design-system tokens and primitives; the app shell (Concept A); gap inbox with
virtualisation, peek and bulk actions; gap detail (Concept C); metrics and sources routes; frontline,
manager (with the Concept B heat grid), analyst and admin routes; all state coverage; Storybook.

**Acceptance**

- Keyboard model works on every list route: `J`/`K`, `Space`, `Enter`, `X`, `Cmd/Ctrl+K`, `Esc`.
- 10,000 gaps remain responsive through pagination and virtualisation.
- Inbox API p95 < 750 ms and common metric query p95 < 1 s on the seeded dataset after warm-up, with
  recorded query plans.
- axe passes on every main route; WCAG 2.2 AA checks pass; reduced motion honoured.
- Screenshots captured at 1440 × 900, 1024 × 768 and 390 × 844 for every major route, reviewed by the
  design-reviewer subagent against [docs/design-system.md](design-system.md), findings fixed.
- Empty, loading, delayed, partial, error, unauthorised and offline-recovery states all render
  correctly and distinctly. A happy path alone is not completion.
- Lint gates hold: no `<style>` over 200 characters, no formatted numeric literals outside fixtures.
- No placeholder buttons on any route marked complete.

---

## Phase F — demo and presenter

**Outcome.** Northstar seeds deterministically, all six scenarios produce their gaps, and the demo
resets safely from CLI and UI.

Work: the seed generator; the six scenarios; role switcher; presenter flow; seed/reset/snapshot/
purge/verify with dry-run and guards; the demo guide. The legacy prototype's runtime is retired here
and its routes are freed.

**Acceptance**

- `pnpm demo:seed` twice changes nothing; the same seed reproduces identical gap ids across machines.
- `pnpm demo:verify` passes all eight assertions in [docs/demo-plan.md](demo-plan.md#verification).
- Purge refuses a non-demo tenant, refuses a mismatched slug, and audits every outcome including
  refusals.
- A failed reset rolls back or restores the last valid snapshot — tested by injecting a failure.
- Presenter mode runs all six stories with deterministic state and reset between them.
- Observed, modelled and fictional demo data are visibly distinguished on every surface.

---

## Phase G — integrations

**Outcome.** Tier 1 complete; Tier 2 production-ready with recorded fixtures.

Work: finish Tier 1 (Stripe fixture + live path, retail POS CSV template, footfall CSV and webhook
template, generic signed webhook collector); Tier 2 adapters (Shopify, GA4, App Store Connect,
Google Play) with recorded fixtures and credential-driven live mode; connector health UI; schema
drift detection and surfacing; reauth and retry flows.

**Acceptance**

- The contract suite passes for every connector in both tiers.
- Every connection card shows a real status; `fixture` mode is visibly labelled and never green.
- Schema drift is detected, surfaced and quarantines affected records — never silent.
- Live mode runs when credentials are present and reports its absence when they are not, rather than
  skipping quietly.
- Connector credential handling and egress review recorded.

---

## Phase H — AI and MCP

**Outcome.** An assistant that explains and cites, and never produces a number.

Work: the structured evidence bundle; the explanation assistant; evaluation fixtures; the read-first
MCP server (`list_metrics`, `get_metric_definition`, `query_certified_metric`, `list_gaps`, `get_gap`,
`get_gap_evidence`, `list_source_health`); separate permissioned write tools with confirmation.

**Acceptance**

- Every answer cites metric, gap and evidence identifiers that resolve and that the UI can open; an
  unresolvable citation causes rejection, not display.
- Evaluation fixtures pass for: correct numeric citation, refusal to claim causation from
  correlation, confidence and assumption disclosure, tenant isolation, prompt injection inside source
  text, unsupported-question handling.
- MCP tools are tenant-aware and apply the same semantic and permission policies as the product API.
- Write tools require explicit permission and confirmation; a read-only token cannot invoke one.
- AISVS checks recorded.

---

## Phase I — hardening

**Outcome.** Honest production readiness, or an honest statement of what is missing.

Work: performance profiling and recorded benchmarks; threat-model review; ASVS L2 and AISVS
checklists; production images; OpenTofu reference; backup and restore test; final visual review;
documentation completion.

**Acceptance**

- All performance targets met with recorded evidence, or missed with a recorded reason.
- No unresolved high-severity security issue; medium and low risks listed honestly.
- Production build passes; container scan and SBOM produced.
- Backup and restore exercised end to end, not just documented.
- Final visual review complete across all three viewports.
- Every item in the brief's 22-point definition of done is either met with evidence or explicitly
  listed as not met.

---

## Documentation deliverables by phase

| Phase | Documents |
| --- | --- |
| A | `README.md` rewrite, `docs/local-development.md` |
| B | ADR updates if the auth boundary shifts |
| C | `docs/runbooks/connector-failure.md`, `docs/runbooks/schema-drift.md` |
| D | `docs/data-dictionary.md` |
| E | `docs/accessibility.md` |
| F | `docs/demo-guide.md`, `docs/runbooks/demo-reset.md` |
| G | Per-connector READMEs |
| H | AI evaluation results |
| I | `docs/deployment.md`, `docs/runbooks/backup-restore.md`, `docs/security-checklist.md` |

## Session protocol

- Session 1: audit, specification, design concepts, architecture, threat model, implementation plan.
  Commit and stop.
- Each implementation phase starts in a fresh named session.
- Read only the master brief, build state, relevant ADRs and the files needed for that phase.
- Use subagents for broad study so the main context stays focused; never let two agents edit the
  same files in parallel.
- `/clear` between unrelated phases; `/compact` only within one phase.
- End each session by updating `docs/build-state.md`, running the phase checks, committing coherent
  work and printing the exact next-session prompt.
- Show command output, test results, record counts, API examples or screenshots. Code inspection is
  not evidence.
