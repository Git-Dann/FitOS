# Demo plan — Northstar Outfitters

A deterministic fictional tenant. Same seed → same record counts, same gap ids, same scenario
outputs, same screenshots. Determinism is a tested property, not an aspiration: `demo:verify` fails
if any expected count or gap id drifts.

Northstar Outfitters is fictional and is labelled as such on every surface where its data appears,
including presenter mode and committed screenshots.

## 1. Tenant shape

| Dimension | Value |
| --- | --- |
| Organization slug | `northstar-outfitters` (flagged `is_demo = true`) |
| Stores | 12 UK stores, `NS-001` … `NS-022`, four size bands, three regions |
| Channels | store, web, ios, android |
| Window | 90 days ending at a fixed anchor date stored in the seed manifest |
| Products | 180 styles, ~600 variants across 6 categories |
| Staff | ~12 per store across 4 roles |
| Campaigns | 10 across paid search, paid social, display, email, organic, affiliate |
| Apps | iOS and Android, 5 released versions in the window |
| Currency | GBP, stored as integer minor units |
| Timezone | Europe/London — the window crosses a BST boundary deliberately |

The window deliberately spans a daylight-saving change so that timezone handling is exercised by the
demo data rather than only by unit tests.

## 2. Record budget

Design target ≈ 1.42 M canonical records, inside the brief's 750 k–1.5 M band. These are the
generator's target counts; `demo:verify` pins the exact figures once the generator exists and fails
on any drift.

| Fact | Target | Derivation |
| --- | --- | --- |
| `fact_digital_session` | 108,000 | 1,200/day × 90 |
| `fact_funnel_event` | 237,600 | 2.2 steps per session |
| `fact_transaction` | 118,800 | 97,200 store (12 × 90 × 90) + 21,600 web |
| `fact_transaction_line` | 285,120 | 2.4 lines per transaction |
| `fact_return` | 9,500 | ~8% of transactions |
| `fact_return_line` | 12,350 | 1.3 lines per return |
| `fact_footfall_observation` | 51,840 | 12 × 90 × 48 (15-min, 12 trading hours) |
| `fact_inventory_snapshot` | 162,000 | 12 × 150 active variants × 90 daily |
| `fact_stock_check` | 5,400 | 12 × 90 × 5 |
| `fact_service_request` | 43,200 | 12 × 90 × 40 |
| `fact_fulfilment_event` | 86,400 | 2 state changes per request |
| `fact_fitting_room_session` | 64,800 | 12 × 90 × 60 |
| `fact_workforce_shift` | 12,960 | 12 × 90 × 12 |
| `fact_capacity_observation` | 51,840 | matches footfall cadence |
| `fact_campaign_spend` | 5,400 | 10 campaigns × 6 channels × 90 |
| `fact_campaign_touchpoint` | 64,000 | |
| `fact_appstore_observation` | 3,600 | 2 platforms × versions × 90 |
| `fact_feedback_observation` | 9,000 | 100/day |
| `fact_metric_observation` | 90,000 | materialised governed metrics |
| **Total** | **≈ 1,421,810** | |

Generation is seeded from a fixed integer with an explicit PRNG — never the language default, never
wall-clock time. Identifiers are derived deterministically (`uuid v5` over a namespace plus a stable
natural key), so gap ids are stable across machines and reseeds.

## 3. Scenarios

Six scenarios, each with the gaps it must produce. `demo:verify` asserts each expected gap exists
with the right type, scope, detector and confidence band. A scenario that does not produce its gap
is a failing test, not a demo tweak.

### Scenario 1 — Saturday capacity leak

Signal: over four consecutive Saturdays at `NS-003`, footfall rises ~35%, fitting-room demand rises
with it, staffed hours stay flat, median service wait rises 2.4×, store conversion falls ~3 pp.

Expected gaps:

| Type | Scope | Detector | Exposure | Confidence |
| --- | --- | --- | --- | --- |
| `staffing_capacity_shortfall` | location NS-003, Saturday | baseline + peer comparison | modelled range | medium |
| `store_conversion_drop` | location NS-003 | peer comparison | modelled range | medium |

The two are correlated, not merged: different metrics, different definitions. The conversion gap
links to the capacity gap as a related gap.

### Scenario 2 — Stock truth gap (vertical slice)

Signal: `fact_inventory_snapshot` shows units available for Pleated Chino, 32 / Charcoal at
`NS-014`; nine staff stock checks over six days fail; seven customer requests go unmet; three
customers accept an alternative.

Expected gaps:

| Type | Scope | Detector | Exposure | Confidence |
| --- | --- | --- | --- | --- |
| `stock_truth_mismatch` | variant × location | source mismatch | modelled range | medium |
| `unmet_demand` | variant × location | ratio threshold | modelled range | medium |

This is the vertical slice the implementation plan builds first, because it carries the strongest
concepts from the existing prototype: ordinal stock confidence, unmet demand as a record, and
alternatives partly accepted. It must produce **one evolving gap with a timeline**, not nine daily
rows — the dedupe test for this scenario is a release gate.

### Scenario 3 — App acquisition leak

Signal: installs rise ~40% after a campaign; activation on iOS 4.2.1 falls ~18 pp against 4.2.0;
first-purchase rate falls; review sentiment declines and crash-related support messages rise in the
same window.

Expected gaps:

| Type | Scope | Detector | Exposure | Confidence |
| --- | --- | --- | --- | --- |
| `app_activation_drop` | channel ios, version 4.2.1 | funnel drop + peer version | modelled range | medium |
| `app_first_purchase_drop` | channel ios | funnel drop | modelled range | low |

Evidence spans three sources — app store, product analytics and commerce — which is the point of the
scenario: the finding is only visible cross-source.

### Scenario 4 — Campaign and store mismatch

Signal: digital audience rises in two regions, website engagement improves, store visits do not rise
as expected.

Expected gap: `campaign_store_response_mismatch`, scope campaign × region, baseline comparison,
confidence **capped at medium** with reason code `attribution_limited`, and the recommended action is
an investigation or a controlled test — never a causal claim. This scenario exists specifically to
demonstrate the product refusing to over-claim, and the presenter script says so out loud.

### Scenario 5 — Return margin leak

Signal: Field Jacket / Stone sells well; its return rate runs 2.1× the category and handling cost
rises with it; revenue looks healthy while gross margin weakens.

Expected gap: `margin_leakage_returns`, scope product variant, financial leakage model, exposure
ranked by **margin**, not revenue. The demo point is that the gap outranks higher-revenue items —
verified by asserting its inbox rank position, not just its existence.

### Scenario 6 — Data-quality fault

Signal: the footfall source for `NS-007` stops reporting on day 61; a connector changes a field from
integer to string on day 74.

Expected gaps:

| Type | Scope | Detector | Exposure | Confidence |
| --- | --- | --- | --- | --- |
| `source_freshness_stall` | source × location NS-007 | freshness | none | high |
| `schema_drift` | source connection | schema drift | none | high |
| `data_completeness_drop` | source × location NS-007 | completeness | none | high |

Data-quality gaps carry no exposure — there is nothing to model — and high confidence, because
absence is directly observed. Their consequence is that the `store_conversion` gap for `NS-007`
appears with reason code `suppressed_by_data_quality`, a capped confidence band and a visible link
to the freshness gap. That linkage is the most important assertion in the whole demo suite: it is
what stops a data outage from looking like calm.

## 4. Demo users

One per role, seeded with development-only auth (magic link or dev-only credential grant). **No
reusable password is committed.** Production mode refuses to seed demo identities and the process
fails at startup if demo auth is enabled while the environment is production.

| User | Role | Lands on |
| --- | --- | --- |
| `frontline@northstar.demo` | frontline | `/frontline` |
| `manager@northstar.demo` | manager | `/inbox` |
| `analyst@northstar.demo` | analyst | `/inbox` |
| `admin@northstar.demo` | admin | `/admin` |
| `owner@northstar.demo` | owner | `/admin` |
| `presenter@northstar.demo` | presenter-demo | `/demo/presenter` |

A local-only role switcher is available on demo tenants. It is gated on `is_demo` server-side, not
on an environment variable in the client.

## 5. Presenter flow

Preserves the strongest asset of the existing prototype. Scenario picker → ordered steps → customer,
frontline, manager, analyst and admin views → presenter notes → role switching → presentation mode
with reduced chrome → deterministic state → reset before each story.

A persistent banner distinguishes observed, modelled and fictional demo data. The Concept B heat
grid opens the Saturday capacity story because it makes pressure legible in one glance; every other
beat runs through the ledger.

Presenter notes carry the operational problem, the retailer's question and the metric at each step —
the structure the prototype's `DemoController` already uses and which works.

## 6. Commands

```bash
pnpm demo:seed        # idempotent; safe to run twice
pnpm demo:reset       # restore the named demo tenant to its snapshot
pnpm demo:snapshot    # capture the current demo tenant as a restore point
pnpm demo:purge       # delete only the named demo tenant
pnpm demo:verify      # assert counts, gap ids and scenario outputs
```

All accept `--tenant <slug>` and `--dry-run`. They may call Python behind the scenes.

Rules, restated as implementation requirements:

- Seed is idempotent.
- Reset restores the named demo tenant to its original snapshot; a failed reset rolls back or
  restores the last valid snapshot.
- Purge deletes only the named demo tenant, requires the exact slug typed as confirmation, and
  refuses any tenant not flagged `is_demo`.
- Production mode blocks fixture seeding by default.
- No command may run against all organizations without a separate break-glass path.
- Every seed, reset and purge writes an audit record — including refusals.
- The admin UI explains exactly what each action will remove, requires typed confirmation for purge,
  and shows progress, result counts and failures.

## 7. Verification

`pnpm demo:verify` asserts:

1. Total canonical record count matches the pinned figure exactly.
2. Per-fact counts match the pinned table.
3. Each of the six scenarios produces its expected gaps, with the expected type, scope, detector
   version and confidence band.
4. Scenario 2 produces **one** stock-truth gap with a multi-entry timeline, not one per day.
5. Scenario 5's margin gap outranks the highest-revenue product gap in the default inbox order.
6. Scenario 6's freshness gap causes the dependent conversion gap to carry
   `suppressed_by_data_quality` and a capped band.
7. Reseeding from the same seed reproduces identical gap ids.
8. Seeding twice changes nothing (idempotence).

Items 4, 6 and 7 are the ones most likely to regress silently, so they run on every CI build rather
than only before a demo.
