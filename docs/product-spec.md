# Product specification — FitOS Gap Intelligence

Status: draft for Session 1. Source of record: [docs/master-build-brief.md](master-build-brief.md).

## 1. Product statement

> FitOS turns fragmented operational data into a governed ledger of gaps, evidence and actions.

The primary object is a **Gap**. The primary experience is a **Gap Ledger** that behaves like an
operational issue system, not a BI dashboard. A chart exists only to explain a gap; it is never the
destination.

## 2. What this product is not

Stated as constraints because each has a strong gravitational pull during implementation:

- Not a chart gallery. No route may exist whose purpose is "show the data".
- Not a chat wrapper. The signed-in home is a work queue, not a prompt box.
- Not a connector marketplace. Connector count is not the value; cross-source evidence is.
- Not an alerting tool. An alert with no owner, no evidence and no measured outcome is noise.
- Not a forecasting product. FitOS quantifies what already happened and what it may have cost. It
  does not predict, and it does not claim savings.

## 3. The nine questions

Every Gap must answer all nine, and the detail view is laid out in this order. A gap that cannot
answer 1–6 must not be created; a gap that cannot yet answer 7–9 is legitimately open work.

| # | Question | Where it comes from |
| --- | --- | --- |
| 1 | What happened? | `observed_value`, `as_of_at`, scope |
| 2 | What was expected or compared? | `expected_value`, detector class and configuration |
| 3 | How large is the difference? | `absolute_delta`, `percentage_delta`, `unit` |
| 4 | What business exposure might it represent? | `exposure_low/base/high` + formula |
| 5 | How reliable is that estimate? | `confidence_score`, `confidence_band`, components |
| 6 | Which records and definitions support it? | `evidence_refs`, `metric_definition_id`, `metric_version` |
| 7 | What action is proposed? | `recommended_actions` |
| 8 | Who owns the action? | `owner_id`, gap action assignment |
| 9 | What changed after the action? | `outcome_id`, post-action measurement window |

## 4. Roles and what each one is for

| Role | Primary job | Default route | Sees exposure? |
| --- | --- | --- | --- |
| `frontline` | Execute the next action on shift | `/frontline` | No |
| `manager` | Decide where to spend the next hour of team capacity | `/inbox` | Yes |
| `analyst` | Interrogate definitions, replay detectors, validate findings | `/inbox` | Yes |
| `admin` | Run connectors, mappings, roles, retention, demo controls | `/admin` | Yes |
| `owner` | Everything admin does, plus billing and org lifecycle | `/admin` | Yes |
| `presenter-demo` | Run a scripted story across roles on demo tenants only | `/demo/presenter` | Yes, labelled fictional |

Permissions are capabilities, never role-name checks in components. A component asks
`can("gap.assign")`, not `role === "manager"`. Capability definitions live in the API and are
mirrored into the client through generated contracts.

The frontline exclusion from exposure is deliberate product policy, not a security afterthought: a
modelled money figure attached to a colleague's individual task changes behaviour in ways the data
cannot justify. It is enforced server-side — exposure fields are omitted from the payload, not
hidden with CSS.

## 5. First pack — Omnichannel Retail Operations

A fictional UK retailer: 12 stores, a commerce website, iOS and Android apps, paid and organic
acquisition, footfall counters, POS, stock snapshots and manual stock checks, rotas, fitting-room
events, campaigns, feedback and support.

### Gap families

Each family names the comparison it makes, because a gap type without a defined comparison is a
metric with an opinion.

| Family | Compares | Primary detector class |
| --- | --- | --- |
| Footfall to conversion | Transactions ÷ footfall vs peer stores and own baseline | Peer / baseline comparison |
| Audience to purchase | Sessions → cart → order | Funnel drop |
| App acquisition to activation | Install → activation → first purchase, split by app version | Funnel drop + peer comparison |
| Demand to stock availability | Requests vs available units at request time | Ratio threshold |
| System stock to observed stock | Snapshot units vs stock-check outcomes | Source mismatch |
| Staffing capacity to service demand | Requests per staff hour vs service wait | Ratio threshold + baseline |
| Customer request to fulfilment | Fulfilled within promise ÷ requests | Ratio threshold |
| Revenue to gross margin | Margin trend against revenue trend, incl. returns and handling | Financial leakage model |
| Campaign spend to attributable result | Spend vs attributable outcome under a declared method | Baseline comparison, low confidence by construction |
| Product trial to keep or return | Fitting-room trials → purchases → returns | Funnel drop |
| Data completeness, freshness and schema quality | Expected vs received; declared vs observed schema | Freshness / completeness / schema drift |

The last family is not a second-class citizen. A data-quality gap suppresses or de-confidences the
business gaps that depend on the same source, and that linkage is visible in the UI.

### Pack contract

A pack is a versioned bundle of: canonical entity requirements, metric definitions, detector
configurations, scenario definitions, role defaults and copy. Adding a pack must not change core
data contracts. Future packs (Digital Product Growth, Venue Operations, Studio Operations) are out
of scope for this branch and exist only as a contract test: the core must not name "retail"
anywhere outside `packs/retail`.

## 6. Surfaces

Routes are specified in [docs/master-build-brief.md](master-build-brief.md#routes). The behavioural
requirements that matter most:

**Gap Inbox** (`/inbox`) — default signed-in view for manager, analyst, admin, owner. Compact rows:
type, title, scope, exposure range, confidence, severity, freshness, owner, status, first/last seen.
`J`/`K` move, `Space` peeks, `X` selects, `Cmd/Ctrl+K` opens the command menu, `Esc` closes. Bulk
assign, bulk status, bulk dismiss. Filters, time window, grouping and selected view live in the URL.

**Gap detail** (`/gaps/[gapId]`) — the nine questions in order, plus evidence timeline, source
lineage, detector explanation, related gaps, comments, audit history. The evidence panel must make
it structurally hard to confuse observed with modelled: they are different components with
different treatment, never the same card with different text.

**Frontline** (`/frontline`) — an operating view for a tablet or phone on shift. Shift status, next
actions, service pressure, request queue, stock exceptions, assigned tasks, promises at risk,
acknowledge and complete. No exposure, no modelling, no analytics chrome.

**Manager** (`/manager`) — operating pressure, highest-value open gaps, location and shift
comparison, staff/service alignment, demand and stock exceptions, assigned actions, recent outcomes.

**Analyst** (`/explore`, `/metrics`) — governed metric explorer, cohort and segment comparison, gap
replay, detector configuration preview, metric lineage, data-quality inspection, query details for
authorised users, saved analyses.

**Admin** (`/admin/*`) — connectors and credentials, schedules, mapping versions, schema drift,
quarantine, metric definitions, detector rules, roles, retention, audit, demo seed/reset/purge.

**Presenter** (`/demo/presenter`) — scenario picker, ordered steps, role switching, presenter notes,
reduced-chrome presentation mode, deterministic state, reset before each story, and a persistent
visual distinction between observed, modelled and fictional demo data. This surface inherits
directly from the existing prototype's strongest asset.

## 7. Concepts carried forward from the prototype

These are product requirements, not migration notes. Each is currently implemented in
`app/ui/fulfilment-engine.ts` and must survive with its semantics intact.

1. **Stock confidence is ordinal, not boolean.** `Confirmed > Likely > Check`, with a tenant-
   configurable minimum. Availability is a claim with a confidence, never a fact.
2. **Retailer policy is configuration.** Enabled fulfilment methods, queue thresholds, batch window,
   maximum promise, minimum stock confidence — all tenant-scoped and versioned.
3. **Capacity gates service options.** Green/Amber/Red derived from queue length against thresholds;
   Red withdraws immediate staff delivery.
4. **Accessibility overrides capacity.** An accessibility need restores staff delivery at Red. This
   rule is non-negotiable and carries a golden test.
5. **An unfulfillable request is a record, not a silence.** Unmet demand is a fact row with a
   reason, feeding both the stock-availability and stock-truth gap families.

## 8. Editorial rules for numbers

Inherited and hardened from the prototype's `ASSUMPTIONS.md` and `KNOWN_LIMITATIONS.md`:

- Observed values state their as-of time and source. Modelled values state low, base, high, formula,
  assumptions and confidence. The two are never rendered by the same component.
- No causal language without an experiment, a declared attribution method or direct observation.
  "Associated with" and "coincides with" are permitted; "caused", "saved" and "increased" are not.
- No savings, ROI or conversion-uplift claim anywhere in the product, including marketing surfaces.
- Currency is stored as integer minor units with an ISO code, and displayed with the organization's
  display locale. Timestamps are stored UTC and displayed in the organization timezone.
- Demo data is labelled fictional on every surface where it appears, including screenshots.

## 9. Acceptance

The product-level definition of done is the 22-point list in
[docs/master-build-brief.md](master-build-brief.md#definition-of-done). Phase-level acceptance
criteria are in [docs/implementation-plan.md](implementation-plan.md).
