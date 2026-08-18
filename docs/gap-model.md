# Gap model

Defines the `Gap` aggregate, its lifecycle, and the exposure, confidence, evidence and
deduplication models. This document is the contract; the API and detector implementations follow it.

## 1. Aggregate

Fields as specified in the brief, annotated with type and rule. Stored in PostgreSQL (control
plane), because gaps have lifecycle, ownership and audit — they are not analytics rows.

| Field | Type | Rule |
| --- | --- | --- |
| `id` | uuid v7 | Sortable by creation. |
| `organization_id` | uuid | Every query is scoped by it; enforced by RLS *and* service layer. |
| `pack_key` | text | e.g. `retail_omnichannel`. |
| `gap_type` | text | Stable key within a pack, e.g. `stock_truth_mismatch`. |
| `title`, `summary` | text | Generated from a template with governed inputs, never free-form AI. |
| `scope_type`, `scope_id` | text, text | `location` / `product_variant` / `channel` / `campaign` / `organization`. |
| `metric_definition_id`, `metric_version` | uuid, int | The **primary** metric. Additional metrics live in `evidence_refs`. |
| `observed_value`, `expected_value` | numeric | Both required. A gap with no comparison is not a gap. |
| `absolute_delta`, `percentage_delta` | numeric | Derived, stored for sortability. `percentage_delta` is null when `expected_value` is 0. |
| `unit` | text | `count`, `ratio`, `currency_minor`, `seconds`. |
| `currency` | char(3) | ISO 4217, non-null when any monetary field is set. |
| `exposure_low`, `exposure_base`, `exposure_high` | bigint | Integer minor units. All three or none. |
| `confidence_score` | numeric(4,3) | 0.000–1.000. Computed, never AI-set. |
| `confidence_band` | enum | `low` < 0.4, `medium` 0.4–0.7, `high` > 0.7. |
| `severity` | enum | `info`, `low`, `medium`, `high`, `critical`. Ranking input, distinct from exposure. |
| `status` | enum | See lifecycle. |
| `owner_id` | uuid, null | Membership id, not user id — ownership is org-scoped. |
| `first_seen_at`, `last_seen_at`, `as_of_at` | timestamptz | `as_of_at` is the observation window end, not the write time. |
| `data_freshness_seconds` | int | `as_of_at` minus the newest contributing source record. |
| `rule_id`, `rule_version`, `detector_run_id` | uuid, int, uuid | Reproducibility triple. |
| `assumptions` | jsonb | Ordered list of `{key, statement, value, source}`. |
| `evidence_refs` | jsonb | Array of evidence references (§5). |
| `recommended_actions` | jsonb | Array of `{key, title, rationale, playbook_id}`. |
| `reason_codes` | text[] | Machine-readable why-this-fired codes. |
| `dedupe_key` | text | See §6. Unique per organization among non-terminal gaps. |
| `created_at`, `updated_at`, `resolved_at`, `dismissed_at` | timestamptz | |
| `outcome_id` | uuid, null | Set on transition into `Resolved`. |

### Invariants

Enforced as database constraints where expressible, and as property tests otherwise.

1. No gap without `metric_definition_id`, `metric_version`, `rule_version`, at least one entry in
   `evidence_refs`, and `as_of_at`.
2. If any of `exposure_low/base/high` is set, all three are set, `low <= base <= high`, `currency`
   is non-null, and `assumptions` is non-empty.
3. `confidence_score` is present whenever exposure is present.
4. `resolved_at` is non-null if and only if `status = Resolved`; likewise `dismissed_at` /
   `Dismissed`. `outcome_id` is non-null when `status = Resolved`.
5. `first_seen_at <= last_seen_at <= as_of_at`.
6. `dedupe_key` is unique per `(organization_id, dedupe_key)` where `status` is not terminal.

## 2. Lifecycle

```text
Detected ──▶ Triaged ──▶ Investigating ──▶ Actioned ──▶ Validating ──▶ Resolved
    │           │              │              │             │
    └───────────┴──────────────┴──────────────┴─────────────┴──────▶ Dismissed
```

- `Detected` — created by a detector run. No human has looked at it.
- `Triaged` — a human has confirmed it is worth attention and set severity/owner.
- `Investigating` — someone is establishing cause. Evidence may be added.
- `Actioned` — an action has been taken; the measurement window has not closed.
- `Validating` — the window has closed and the outcome is being measured.
- `Resolved` — an outcome record exists. The outcome may be "no measurable change"; resolution does
  not mean success.
- `Dismissed` — reachable from any non-terminal state, requires a reason code and a free-text note.

Rules: every transition is permission-checked, written to the audit log with actor, before/after and
request id, and carries an optimistic-concurrency version check. A detector re-firing on a gap in
`Actioned` or later does not reopen it — it appends to the evidence timeline and updates
`last_seen_at`. Reopening is an explicit human action.

## 3. Exposure model

Never present a single precise financial value when the inputs do not support that precision.

Stored per gap: `low`, `base`, `high`, formula key, formula version, assumptions, source metric
references, confidence and data freshness. Rendered as a range with the band always visible.

### Worked example — unmet demand

```text
exposure = unmet_request_count
         × median_item_gross_margin_minor
         × recovery_probability
```

| Input | Low | Base | High | Source |
| --- | --- | --- | --- | --- |
| `unmet_request_count` | observed | observed | observed | fact table, exact |
| `median_item_gross_margin_minor` | p25 | median | p75 | governed metric over the scope window |
| `recovery_probability` | 0.15 | 0.35 | 0.55 | tenant assumption, default from pack config |

`recovery_probability` is an assumption, not an observation, and is recorded as such with its
source. Changing it is an admin action that writes an audit record and re-runs affected exposure
calculations — it never silently changes historical gap values, because `formula_version` pins them.

### Rules

- Exposure is bounded by observability. If any input is modelled, the whole exposure is modelled and
  labelled so.
- `high / low` ratio above a pack-configured limit (default 5×) forces `confidence_band = low` and
  adds reason code `wide_exposure_interval`.
- Exposure never appears without its confidence band adjacent to it, in every surface including
  exports and the API payload.
- Exposure is not a savings claim. Copy is "estimated exposure", never "potential savings".
- Frontline role: exposure fields are omitted server-side.

## 4. Confidence model

`confidence_score` is a weighted product of component scores, each in 0–1, each stored in the
evidence record so the UI can show the breakdown and the AI layer can explain — but never set — it.

| Component | Measures | Default weight |
| --- | --- | --- |
| `sample_size` | Observation count against the detector's minimum | 0.20 |
| `completeness` | Received ÷ expected records in the window | 0.20 |
| `freshness` | Decay against the source's expected latency | 0.15 |
| `source_agreement` | Cross-source concordance where two sources measure the same thing | 0.15 |
| `metric_stability` | Variance of the metric over the baseline window | 0.10 |
| `detector_fit` | Detector-specific fit statistic (e.g. residual against seasonal model) | 0.15 |
| `identity_match` | Match quality where the gap depends on joining identities | 0.05 |

Components that do not apply to a detector are dropped and the remaining weights renormalised; the
dropped set is recorded. Any component below 0.2 caps the overall band at `medium`; any below 0.1
caps it at `low`.

Attribution-based gaps (campaign families) are capped at `medium` by construction and carry reason
code `attribution_limited`, because a correlation between spend and outcome does not establish the
link. This is a hard rule, not a heuristic.

## 5. Evidence

Every gap links to versioned evidence references. A reference contains:

```text
source_connection_id
source_record_locator          object key + byte range, or table + primary key
canonical_entity
canonical_record_id
metric_definition_id
metric_version
query_hash                     hash of the exact compiled query
query_parameters
observation_window             [start, end)
captured_at
sensitivity_classification     public | internal | confidential | restricted
```

From a gap a user must reach: the metric definition and version, the source connection and its
health, the detector version and configuration, and the supporting records — without guessing how a
number was produced. Raw payloads are immutable, so an evidence reference remains resolvable even
after mappings change; a re-mapped canonical record gets a new version rather than overwriting.

Evidence carries a sensitivity classification and the API filters references the caller may not
resolve, returning the reference metadata with a `redacted` marker rather than silently dropping it —
a missing row is indistinguishable from a data error, which is worse than an explicit refusal.

## 6. Deduplication and correlation

One stock discrepancy pattern is one evolving gap with a timeline, not thirty near-identical rows.

**Dedupe key.** `hash(organization_id, pack_key, gap_type, scope_type, scope_id, detector_rule_id)`.
Deliberately excludes the observation window and the values, so the same problem in the same scope
on consecutive days is the same gap.

**On detector output.** If an open gap with the same key exists: update `observed_value`,
`expected_value`, deltas, exposure, confidence, `last_seen_at`, `as_of_at`; append an evidence
timeline entry; leave `first_seen_at`, `status` and `owner_id` alone. Otherwise create.

**Correlation.** After dedupe, a correlation stage links gaps that share scope, window and
contributing sources into a `related_gaps` graph — for example a footfall-freshness gap and the
store-conversion gap that depends on it. Related gaps are shown, never merged; merging would lose
the distinct metric definitions.

**Suppression.** A gap whose contributing source has an open freshness or completeness gap is
created with reason code `suppressed_by_data_quality`, a capped confidence band and a visible link
to the data-quality gap. It is not hidden — hiding it would make a data outage look like calm.

Every detector run records candidates produced, candidates suppressed and dedupe decisions, so
suppression is auditable rather than invisible.

## 7. Actions and outcomes

An action is a separate record: `{id, gap_id, title, playbook_id, assignee_id, due_at, status,
created_by, created_at, completed_at}`. An outcome is `{id, gap_id, action_id, measurement_window,
metric_definition_id, metric_version, value_before, value_after, delta, method, notes, recorded_by}`.

`method` is one of `observed`, `pre_post`, `controlled_test`. A `pre_post` outcome may not use
causal language anywhere in the product; only `controlled_test` may, and only within its declared
design. "No measurable change" is a first-class, non-pejorative outcome and must be as easy to
record as a positive one — otherwise the ledger becomes a success-reporting instrument.
