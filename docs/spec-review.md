# Specification review

The brief requires the Session 1 documents to be reviewed for contradictions before implementation
begins. This is that review. Each item is a real conflict between two things the brief asks for, or
between the brief and what the repository actually is — not a stylistic preference.

Fourteen items. Eight are resolved here or in an ADR; four are unresolved tensions to measure rather
than argue about; two are open questions for the user.

---

## Resolved

### R1 — Branch name

The brief opens with `git checkout -b feat/gap-intelligence-platform`. This session's operating
mandate specifies `claude/md-file-review-67empl`.

**Resolved:** the session mandate wins; work proceeds on `claude/md-file-review-67empl`. The branch
name has no bearing on any deliverable.

### R2 — Cloudflare Workers versus the required platform services

The repository targets Cloudflare Workers (`vinext`, `worker/index.ts`, D1/R2 bindings). The brief
requires FastAPI, Temporal, ClickHouse, MinIO, dbt and Docker Compose, none of which can run there.

**Resolved:** [ADR 0008](adr/0008-hosting-target-and-legacy-runtime.md). Containers for the platform;
the Workers runtime is preserved intact in `legacy/fitos-prototype/`; R2 survives as an S3-compatible
option behind the storage adapter.

### R3 — Better Auth (TypeScript) versus `/auth` in FastAPI

The brief names Better Auth as the auth implementation and separately lists `/auth` among the FastAPI
resource groups. Read literally, that is two login systems.

**Resolved:** [ADR 0005](adr/0005-auth-provider.md). Better Auth owns identity and JWT issuance;
FastAPI verifies JWKS and owns authorisation. `/auth` in the API is session introspection, capability
discovery and organization switching — not a second login.

### R4 — One metric per gap versus multi-metric evidence

The `Gap` aggregate has a single `metric_definition_id` and `metric_version`. But the exposure model
requires "source metrics" (plural), and a funnel-drop or campaign-mismatch gap is defined across
several metrics by construction.

**Resolved:** the aggregate field is the **primary** metric — the one whose deviation defines the gap
and by which it is ranked and grouped. Every other contributing metric appears in `evidence_refs`
with its own `metric_definition_id` and `metric_version`. Documented in
[docs/gap-model.md](gap-model.md#1-aggregate). Without this rule the field is ambiguous and two
detectors would populate it differently.

### R5 — "Evidence required" versus gaps whose evidence is an absence

The brief requires that no gap exists without evidence. Scenario 6 creates a freshness gap precisely
because a source *stopped* sending records. There are no records to point at.

**Resolved:** an evidence reference for an absence points to the source connection's declared
cadence, the last successfully received record with its `captured_at`, and the query proving the
window is empty. The `observation_window` is the interval in which nothing arrived. This satisfies
the invariant honestly rather than by exemption — and it is the right design, because "we expected N
and received 0" is a stronger claim than "nothing is here."

### R6 — Frontline exposure: hard exclusion or permission?

The product rules imply frontline never sees exposure. The brief's frontline section says to keep
modelling out "unless the role has permission and a direct need."

**Resolved:** implemented as the capability `gap.view_exposure`, not granted to `frontline` by
default and grantable per organization. The default is the strict reading; the mechanism allows the
exception the brief permits. Enforced server-side, so it holds for the API, exports and the AI layer
at once.

### R7 — SQL for authorised analysts versus no browser SQL to ClickHouse

The analyst view should show "SQL or query details for authorised users", while the analytics rules
forbid unrestricted user-written SQL reaching ClickHouse from the browser.

**Resolved:** the analyst surface **displays** the compiled query — the one the governed layer
generated, with its parameters and query hash — as read-only provenance. It is not an execution
path. Ad-hoc analysis happens through the governed metric explorer with allowlisted dimensions and
filters.

### R8 — Route collision on `/demo`

The legacy prototype owns `/demo`, `/demo/customer`, `/demo/associate`, `/demo/manager`. The target
route list owns `/demo` and `/demo/presenter`.

**Resolved:** the legacy runtime moves to `legacy/fitos-prototype/` in Phase A and stops serving
routes from the platform app. Its role surfaces reappear as `/frontline`, `/manager` and the
presenter flow. Sequenced so the legacy build stays runnable until Phase F.

---

## Unresolved tensions — to be measured, not argued

### T1 — Demo volume versus local performance targets

≈1.42 M canonical records, five infrastructure containers (PostgreSQL, ClickHouse, MinIO, Temporal,
Cube), an inbox p95 under 750 ms and a metric query p95 under 1 s, all on "a normal local development
machine". These are simultaneously satisfiable, but not by accident.

**Action:** measure container memory and startup time in Phase A before the dataset exists, and
record inbox and metric benchmarks in Phase D with query plans. If the targets are missed, the
honest options are a smaller default seed with an opt-in full seed, or documented minimum hardware —
not quietly relaxed targets.

### T2 — Visual regression in CI versus when baselines first exist

The CI requirements list visual regression on approved baselines. No route exists before Phase E.

**Action:** the visual-regression job is added in Phase E, not Phase A, and Phase A's CI skeleton
declares the job as pending rather than passing vacuously. A green check for a job with no baselines
is worse than no check.

### T3 — 12 detector classes versus one working vertical slice

The brief lists twelve detector classes; the vertical-slice principle says build one path completely
first.

**Action:** Phase D implements source mismatch and ratio threshold (what Scenario 2 needs) against
the full detector interface, then adds the remaining ten. The interface is designed for twelve from
the start; only two are implemented when the slice closes. Recorded so a later reader does not read
Phase D's acceptance list as the whole detector story.

### T4 — Dependency advisories in the legacy tree

The repository carries 21 advisories (16 high), essentially all transitive through the Cloudflare
toolchain that the platform will not use. A CI audit gate that fails on high-severity findings would
fail on day one, on code that is preserved rather than maintained.

**Action:** the legacy tree keeps its own lockfile outside the workspace and is excluded from the
audit gate with a **dated, recorded exception**, not silently. The platform graph is gated normally.
Revisit if the legacy tree ever ships to a live host.

---

## Questions answered by the user (2026-08-14)

### Q1 — Is the Vercel deployment live? — **answered: live, but not worth preserving**

`design-qa.md` references `https://fitos-retail-operations.vercel.app/demo/manager`. The user
confirms it is live but that it carries no value now the project is moving to production.

**Resolved:** Phase A moves the prototype into `legacy/` without protecting the deployment. No
Vercel project reconfiguration is required and none should be attempted. If the URL breaks, that is
the intended outcome. Risk 6 is closed.

### Q2 — Is the existing palette fixed? — **answered: no, replace it**

The user asks for a near-black neutral with an orange accent, closer in character to Linear.

**Resolved:** [docs/design-system.md](design-system.md) §2 is rewritten around a cool near-black
neutral ramp (`#0B0C0E` canvas) and an orange accent (`#F75F14` fill, `#FF7A3C` on dark text).
**Dark becomes the default theme**; light remains a tested peer. Values live in
[`docs/design-tokens/tokens.json`](design-tokens/tokens.json) and are verified by
`node docs/design-tokens/check-contrast.mjs` — 31 pairs, all passing, exit 0.

Three findings came out of measuring rather than asserting, and are recorded because each one would
otherwise have been discovered in Phase E:

1. **White on orange fails AA** at 3.90:1. The label on an accent fill is near-black in *both*
   themes, at 6.15:1. There is no theme where a white-on-orange button is acceptable.
2. **Elevation reverses between themes.** Dark conveys it by background luminance, since shadows are
   invisible on near-black; light inverts it — white panels on a tinted ground, separated by border
   and shadow. Implementing one and letting the other inherit produces a flat light theme.
3. **Orange accent collides with amber severity** at 1.65:1 relative luminance, both warm. Resolved
   by role separation, not hue tuning: accent means interaction only, never "warning"; severity
   always carries an icon and a text label. The collision is asserted in the checker's output so it
   cannot be quietly forgotten.

The Linear reference stays consistent with the brief, which permits Linear as an interaction
reference and forbids copying its colours: this takes the density and near-black character, and the
orange accent is deliberately not Linear's blue-violet.

---

## Consistency checks passed

Checked and found consistent, recorded so they are not re-litigated:

- Six seeded scenarios in the demo plan match "all six seeded scenarios" in the definition of done.
- Gap lifecycle states match between the brief, the gap model and the API resource groups.
- The metric list (19 metrics) covers every metric named by the eleven gap families.
- Every canonical fact named in the brief has a grain, dimensions and a physical rule in the data
  contracts.
- Every route in the brief's route list has an owning surface in the product spec.
- The nine Gap questions map one-to-one onto aggregate fields.
- Data-quality gaps carrying no exposure does not violate "no modelled financial value without low,
  base, high, assumptions and confidence" — that rule constrains modelled values, and a null exposure
  is not one.
- The default inbox sort is severity group, then exposure base descending, then freshness. `severity`
  and exposure are separate fields with separate purposes and both are used.
