# Repository audit

Audit date: 2026-08-14. Branch: `claude/md-file-review-67empl`. Base commit: `439a0df`.

Everything in this document that claims a command result was run in this session. Commands and
outputs are quoted in [Verified evidence](#verified-evidence). No claim is made about code that
was not executed.

## 1. What this repository is today

A single-package browser prototype, not a platform. It began life as the
`site-creator-vinext-starter` Cloudflare template — `package.json` still carries that name — and
the FitOS product was built directly on top of the starter without restructuring it.

| Property | Value |
| --- | --- |
| Package name | `site-creator-vinext-starter` (never renamed) |
| Package manager | npm, `package-lock.json` committed |
| Framework | Next.js 16.2.6 App Router, React 19.2.6 |
| Runtime | Cloudflare Workers via `vinext` 0.0.50 + `@cloudflare/vite-plugin` |
| Styling | Tailwind CSS 4.2.1 present, but most styling is inline `<style>` string literals |
| Database | Drizzle + D1 configured; `db/schema.ts` is intentionally empty (4 lines) |
| Application source | ~4,900 lines across 13 files in `app/` |
| Tests | 5 rule tests (`tests/fulfilment.test.ts`), 3 render tests (`tests/rendered-html.test.mjs`) |
| Auth | None. `app/chatgpt-auth.ts` is unused starter scaffolding |
| Backend | None. `worker/index.ts` is the unmodified starter entry point |

### Routes

```text
/                 marketing home        app/ui/Marketing.tsx
/platform         platform explainer    app/ui/Marketing.tsx
/pilot            commercial story      app/ui/PilotStory.tsx        (309 lines)
/demo             presenter controller  app/ui/DemoController.tsx    (63 lines)
/demo/customer    customer surface      app/ui/CustomerExperience.tsx (692 lines)
/demo/associate   frontline surface     app/ui/AssociateOperations.tsx (16 lines + shared shell)
/demo/manager     manager surface       app/ui/ManagerAnalytics.tsx  (255 lines)
```

`app/ui/FitOSApp.tsx` (806 lines) is the shared shell, design tokens, status chip and the bulk of
the global CSS. It is the single largest file and mixes layout, styling, copy and state.

## 2. Product concepts worth preserving

These are the genuinely valuable outputs of the prototype and they map directly onto the target
platform. They should survive the rewrite as data, rules and scenario definitions — not as
components.

1. **Stock confidence as a first-class signal, not a boolean.** `Confirmed | Likely | Check` with a
   configurable minimum threshold is exactly the "system stock vs observed stock" gap family. It is
   the strongest idea in the repository.
2. **Retailer policy as configuration.** `RetailerConfig` (enabled methods, queue thresholds, batch
   window, maximum promise, minimum stock confidence) is a genuine tenant-configuration boundary.
   It becomes detector configuration and pack configuration.
3. **Capacity → service degradation → fulfilment choice.** `capacityFromQueue()` plus the
   Green/Amber/Red gating in `rankFulfilment()` is the seed for the staffing-capacity-to-service-
   demand gap family.
4. **Accessibility as a policy override, not a nice-to-have.** `accessibilityNeed` re-enables staff
   delivery even at Red capacity. This is a real, tested rule and it must not be lost.
5. **Unmet demand as a recorded event.** The prototype records a request that could not be
   fulfilled rather than discarding it. That is the missed-demand fact table.
6. **Role-based storytelling.** `/demo` with ordered steps, presenter notes and role switching is
   the single most demonstrable asset here and the brief explicitly asks to preserve it.
7. **Honest labelling discipline.** `ASSUMPTIONS.md` and `KNOWN_LIMITATIONS.md` already refuse
   savings and conversion claims, and the ROI panel is captioned as a caveated missed-demand model
   rather than a forecast. This editorial standard is the cultural seed of the exposure model.

## 3. Code worth reusing

Only one module survives contact with the target architecture as code.

**`app/ui/fulfilment-engine.ts` (72 lines).** A pure, dependency-free, deterministic ranking
function with an injected config object and five passing tests. It has no React import, no I/O and
no global state. It should be ported — semantics intact — into the Python detector/rules layer, or
kept in TypeScript inside `packages/contracts` if the fulfilment ranking stays a product-side
concern. Its five test cases become golden fixtures either way.

**`app/ui/data.ts` (41 lines).** Not reusable as code, but valuable as a *specification of shape*:
product/room/request/associate records, barcode and SKU conventions, and the UK retail vocabulary.
It becomes the seed generator's dimension definitions.

**`tests/fulfilment.test.ts`.** Five behavioural assertions worth preserving verbatim as detector
golden fixtures, especially the accessibility-override and policy-disables-a-method cases.

Everything else is presentation.

## 4. Code that should be replaced

| Item | Reason |
| --- | --- |
| `app/ui/FitOSApp.tsx`, `CustomerExperience.tsx`, `ManagerAnalytics.tsx`, `PilotStory.tsx`, `AssociateOperations.tsx` | Each contains a minified CSS string literal inside a `<style>` element — some exceeding 4,000 characters on a single line. Directly violates the brief's "no large CSS strings inside React components" and "no large component containing unrelated product, data and styling logic". |
| Hard-coded analytical values in components | `ManagerAnalytics.tsx:109` renders `£1.1k` as "indicative demand" and `:234` repeats it in prose; `7` unmet requests, `14–15` peak hours, the `queueBars = [35,54,42,68,88,79,57]` array and a `conic-gradient(... 0 71%, ...)` delivery ring are all literals in JSX. Violates "no hard-coded analytical values in React components" and gives a modelled money figure with no low/base/high, no assumptions and no confidence. |
| `package.json` identity and scripts | Still named `site-creator-vinext-starter`. `npm test` is broken (see below). No `typecheck`, `verify`, `test:e2e`, `test:visual` or `demo:*` scripts exist. |
| `worker/index.ts`, `db/`, `examples/d1/`, `app/chatgpt-auth.ts`, `.openai/hosting.json` | Unmodified starter scaffolding for a runtime the target architecture does not use. Not FitOS code. |
| `README.md` | Still the vinext starter README. Describes ChatGPT sign-in helpers and D1 bindings; says nothing about FitOS. |
| Root-level PNG artefacts | `design-qa-*.png` — four files, ~1.5 MB total, committed at repository root. Belong under `docs/` or a screenshot baseline directory. |

## 5. Data and security gaps

The prototype is a static browser demo, so most of these are absences rather than defects. They
are listed because the target platform must supply every one of them.

- **No tenancy of any kind.** No organization concept, no membership, no scoping. Every number is a
  module-level constant shared by all visitors.
- **No authentication or authorisation.** All seven routes are public. The role surfaces at
  `/demo/customer`, `/demo/associate` and `/demo/manager` are URLs, not permissions — anyone can
  open the manager view.
- **No server-side state, no audit log, no lineage.** Nothing records who saw or changed what.
- **No source of truth for numbers.** Metrics are literals in JSX, so there is no metric
  definition, no version, no as-of time and no path from a displayed number to a record.
- **Modelled money presented as a point estimate.** The `£1.1k` figure is captioned "indicative"
  but carries no range, formula, assumption set or confidence. Under the target rules this is a
  blocking product violation, not a copy tweak.
- **Dependency exposure.** `npm audit` reports 21 vulnerabilities (16 high, 4 moderate, 1 low),
  almost entirely transitive through the Cloudflare toolchain (`wrangler`, `miniflare`, `ws`,
  `sharp`/libvips, `@esbuild-kit/core-utils`). These are build and dev-time dependencies, but they
  are unpatched and there is no CI audit gate.
- **No CI.** No `.github/workflows` directory exists. Nothing prevents a broken build from landing —
  and in fact one already has (see below).
- **Lead form goes nowhere.** `KNOWN_LIMITATIONS.md` correctly discloses that pilot-form entries
  stay in the browser session. Any future version that actually collects contact details acquires
  a privacy obligation the current codebase has no machinery for.

### Verified regression: `npm test` is broken

Commit `0d530e2` "Configure Vercel production build" (31 Jul 2026) changed `build` from
`vinext build` to `next build` and added `build:vinext`. The `test` script still runs
`npm run build && node --test tests/rendered-html.test.mjs`, and the smoke test imports
`../dist/server/index.js` — an artefact only `vinext build` produces. `next build` writes `.next/`.

So `npm test` has failed on every commit since 31 July. Confirmed both directions in this session:
`npm test` fails 2 of 3, and `npm run build:vinext` followed by the same test file passes 3 of 3.
The test content is fine; the script wiring is wrong. This is the clearest evidence that the
repository needs CI before it needs features.

## 6. Design strengths and weaknesses

**Strengths.** The visual language is calm, restrained and already close to the brief's stated
preferences: an off-white and deep-green neutral system, one accent, semantic status colours, no
gradients, no glass, no glow, no decorative sparkle. `design-qa.md` records a real design review
that deliberately removed a dense reporting wall in favour of one priority decision — the correct
instinct and evidence that the design process here has judgement. Copy is disciplined: it states a
decision, its evidence, or a next action. Motion is minimal. The prototype avoids nearly every item
on the brief's "avoid" list.

**Weaknesses.** The typographic scale is a marketing scale, not a product scale —
`clamp(45px, 5.8vw, 74px)` headlines inside a signed-in operational view, which the brief names
explicitly as something to avoid. Density is low: the manager view spends a full viewport on three
numbers. There is no keyboard model, no command menu, no list/peek interaction, no saved views and
no focus-state system — the entire Linear-style interaction layer is absent. Tokens exist only as
repeated hex literals inside CSS strings (`#284e46`, `#66716e`, `#d9dfdc` recur across five files),
so there is no theme, no dark mode and no way to change the palette safely. Charts are CSS
`div`s with no scale, axis, source or as-of time.

## 7. Migration risks

1. **Runtime incompatibility is the largest risk.** The current deploy target is Cloudflare Workers
   (`vinext`, `worker/index.ts`, D1/R2 bindings) with a second Vercel-oriented `next build`. The
   target architecture requires FastAPI, Temporal, ClickHouse, MinIO and dbt — none of which can run
   on Workers. This is not a refactor; it is a different platform. Resolved in
   [ADR 0008](adr/0008-hosting-target-and-legacy-runtime.md).
2. **Package-manager switch.** npm with a committed `package-lock.json` must become pnpm with a
   committed `pnpm-lock.yaml`. Straightforward, but it invalidates the existing lockfile and the
   only reproducible dependency record the repository has.
3. **Route collision.** The legacy prototype owns `/demo`, `/demo/customer`, `/demo/associate`,
   `/demo/manager`. The target owns `/demo` and `/demo/presenter`. The legacy runtime must move to
   `legacy/fitos-prototype/` before the new shell claims those paths.
4. **History preservation.** Use `git mv` for the move so blame survives. The four root-level PNGs
   are large binaries; moving rather than deleting keeps the repository size but preserves the
   design-QA record.
5. **Losing the demo during the rewrite.** The prototype is currently the only demonstrable asset.
   The vertical-slice-first sequencing in the implementation plan exists to keep something
   demonstrable at every commit; the legacy build must stay runnable until Phase F replaces it.
6. **Demo dataset scale versus local practicality.** 750k–1.5M canonical records with a p95 under
   750 ms on a laptop is achievable with ClickHouse but only with deliberate ordering keys and
   pre-aggregation. Profile before the dataset grows, not after.
7. **Fictional-data honesty.** Northstar Outfitters is fictional and must be labelled as such in
   every surface, including screenshots. The prototype's existing labelling discipline is the
   standard to hold.

## 8. Proposed repository migration

```text
legacy/fitos-prototype/          git mv of app/, worker/, db/, examples/, build/,
                                 vite.config.ts, next.config.ts, drizzle.config.ts,
                                 tests/, public/, and the starter README
docs/                            brief, audit, specification set, ADRs, runbooks
docs/screenshots/legacy/         git mv of the four design-qa-*.png files
apps/web                         new Next.js product application
apps/storybook
services/api  services/worker  services/semantic
packages/ui  contracts  charts  demo  config
connectors/sdk + per-connector packages
data/dbt  data/seeds  data/contracts
infra/compose  infra/opentofu  infra/scripts
```

Three files move up rather than into legacy, because their content is product truth rather than
prototype implementation: `ASSUMPTIONS.md`, `KNOWN_LIMITATIONS.md` and `DATA_MODEL.md` are folded
into `docs/product-spec.md` and `docs/data-contracts.md` during Phase A, with the originals kept in
`legacy/fitos-prototype/` for provenance.

`fulfilment-engine.ts` and its test file are the exception to the wholesale move: they are copied
forward into the new tree in Phase D as detector inputs, and the copy is what gets maintained.

## Verified evidence

All commands run at `/home/user/FitOS` on branch `claude/md-file-review-67empl`, commit `439a0df`,
Node 22, npm 10.9.7.

```console
$ npm ci
added 601 packages, and audited 602 packages in 46s
21 vulnerabilities (1 low, 4 moderate, 16 high)

$ npm run test:rules
# tests 5
# pass 5
# fail 0

$ npm run lint
(no output — clean)

$ npx tsc --noEmit
(no output — clean)

$ npm test
not ok 3 - serves every public product route
  error: "Cannot find module '/home/user/FitOS/dist/server/index.js'"
  code: 'ERR_MODULE_NOT_FOUND'
# tests 3
# pass 1
# fail 2

$ npm run build:vinext && node --test tests/rendered-html.test.mjs
Build complete. Run `vinext start` to start the production server.
# tests 3
# pass 3
# fail 0
```

Interpretation: lint, type checks and the rules tests are genuinely clean. The repository's
headline `npm test` command has been broken since 31 July 2026 for a scripting reason, not a code
reason. Nothing else in this audit is asserted from execution — the UI was read, not run, and no
claim about its runtime behaviour appears above.
