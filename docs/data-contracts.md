# Canonical data contracts

Defines the layers, the event envelope, canonical facts and dimensions, and the governed metric
contract. Contracts are declared once in `data/contracts/` and generated into Python (Pydantic v2)
and TypeScript (Zod + types). Nothing hand-maintains a duplicate of a contract.

## 1. Layers

```text
raw          immutable source payloads in object storage        never mutated
staging      typed, parsed, one row per source record           mapping-version tagged
canonical    typed facts and dimensions in ClickHouse           conformed, deduplicated
governed     dbt models + Cube semantic layer                   the only source of metric values
```

Rules that hold across every layer:

- Corrections happen forward. A wrong value is fixed by a new mapping version and a re-run, never by
  editing raw or overwriting a canonical row in place.
- Every canonical row carries `lineage_ref` back to the raw object and the mapping version that
  produced it.
- No product code reads raw or staging. The UI reads governed; detectors read canonical and
  governed. This boundary is enforced by a lint rule on import paths.

## 2. Event envelope

The envelope exists for lineage and routing. It is deliberately **not** the storage model —
business data goes into typed facts. Forcing everything into one wide event table produces a schema
that is expensive to query and impossible to test.

```text
event_id                 uuid v7
organization_id          uuid
source_key               text          e.g. shopify, ga4, footfall_csv
source_connection_id     uuid
source_record_id         text          natural key at the source
source_schema_version    text
event_type               text
occurred_at              timestamptz   when it happened in the world
ingested_at              timestamptz   when we pulled it
received_at              timestamptz   when it hit our edge (webhooks)
entity_type, entity_id   text, text
location_id              text, null
channel_id               text, null
product_id               text, null
campaign_id              text, null
anonymous_subject_id     text, null    pseudonymous, salted per organization
amount                   int64, null   minor units
currency                 char(3), null
quantity                 numeric, null
properties               json
data_quality_flags       array(text)
lineage_ref              text          raw object key + mapping version
```

Three timestamps, not one. `occurred_at` drives analysis, `ingested_at` drives freshness, and
`received_at` distinguishes a slow source from a slow pipeline. Collapsing them makes late-arriving
data indistinguishable from a broken connector.

## 3. Canonical facts

| Fact | Grain | Key dimensions | Notes |
| --- | --- | --- | --- |
| `fact_transaction` | one order | date, location, channel, campaign, subject | Money in minor units + ISO code. |
| `fact_transaction_line` | one line | + product variant | Carries unit cost for margin. |
| `fact_return` / `fact_return_line` | one return / line | + original transaction | Handling cost is a modelled input, flagged as such. |
| `fact_footfall_observation` | counter × 15 min | date, location | Interval, not instant. Expected cadence drives freshness. |
| `fact_digital_session` | one session | date, channel, device, campaign, subject | |
| `fact_funnel_event` | one step | + session, step key | Ordered steps; step keys are pack-defined. |
| `fact_appstore_observation` | store × app × version × day | date, channel, app version | Installs, activations, crashes, ratings. |
| `fact_inventory_snapshot` | variant × location × snapshot | date, location, product variant | System belief about stock. |
| `fact_stock_check` | one manual check | + staff member | Observed truth. Pairs with the snapshot for the mismatch detector. |
| `fact_service_request` | one request | date, location, product variant, subject | Includes unmet requests with a reason. |
| `fact_fulfilment_event` | one state change | + request, method | Promise made, promise met/missed. |
| `fact_fitting_room_session` | one session | date, location, room, subject | From the FitOS prototype concepts. |
| `fact_workforce_shift` | one shift | date, location, staff member, role | Planned and actual. |
| `fact_capacity_observation` | location × 15 min | date, location | Derived queue/capacity state. |
| `fact_campaign_spend` | campaign × day × channel | date, channel, campaign | |
| `fact_campaign_touchpoint` | one touchpoint | + subject | Attribution inputs only; never a causal claim. |
| `fact_feedback_observation` | one item | date, location, channel, product | Free text is a prompt-injection surface — see threat model. |
| `fact_metric_observation` | metric × grain × window | all | Materialised governed metric values for detector inputs. |

### Dimensions

`dim_date`, `dim_time_of_day`, `dim_organization`, `dim_source`, `dim_channel`, `dim_location`,
`dim_product`, `dim_product_variant`, `dim_campaign`, `dim_staff_member`, `dim_role`,
`dim_subject` (pseudonymous).

Dimensions are slowly-changing type 2 where the attribute affects historical analysis
(`dim_product_variant.cost_price`, `dim_location.floor_area`) and type 1 elsewhere.

### ClickHouse physical rules

- Partition by `(organization_id, toYYYYMM(occurred_at))`.
- Order by the actual query pattern, typically
  `(organization_id, location_id, occurred_at)` — never by `event_id`.
- `ReplacingMergeTree(ingested_at)` on the source natural key for idempotent re-ingestion, so a
  duplicate webhook or a connector replay cannot create a duplicate fact.
- Incremental materialized views for common aggregates. Projections only after profiling.
- Explicit TTL and tiering per fact.
- Every query carries a row and time limit; the governed query layer injects
  `organization_id` — it is never supplied by the caller.
- No user-written SQL reaches ClickHouse from the browser.

## 4. Personal data

Direct personal data stays out of the analytics plane unless a documented use case requires it.

- Subjects are pseudonymous: `anonymous_subject_id = HMAC(org_salt, source_identifier)`, salt held
  in the secret manager, never in the analytics store.
- Every field carries a sensitivity classification: `public | internal | confidential | restricted`.
- Free-text customer feedback is `confidential` by default and is never sent to the AI layer without
  passing the untrusted-content boundary described in the threat model.
- Retention is per fact and per organization, with deletion jobs that also purge raw objects.
- Identity resolution across sources produces a match-quality score that feeds the confidence model
  and is never treated as certain.

## 5. Governed metric contract

Every product metric is defined as code, version controlled, and serves the UI, exports, API and AI
tools from one definition. Formulas are never reimplemented in React.

```yaml
key: unmet_request_rate
name: Unmet request rate
description: >
  Share of fitting-room service requests that could not be fulfilled by any enabled method
  within the retailer's maximum promise window.
owner: retail-pack
grain: [date, location]
measure_expression: >
  countIf(fulfilment_status = 'unmet') / nullIf(count(), 0)
dimensions: [date, location, channel, product_variant, staff_role]
allowed_filters: [date, location, channel, product_variant]
source_models: [fct_service_request, fct_fulfilment_event]
join_paths:
  - from: fct_fulfilment_event
    to: fct_service_request
    on: request_id
unit: ratio
currency_policy: not_applicable
timezone_policy: organization_display_timezone
null_policy: exclude_null_denominator
valid_from: 2026-01-01
valid_to: null
version: 1
sensitivity: internal
quality_tests: [not_null, between_0_and_1, denominator_min_30]
examples:
  - filters: {location: NS-014, date: 2026-05-16}
    expected: 0.184
```

Rules:

- Changing a formula increments `version` and sets `valid_to` on the old one. Old versions stay
  resolvable forever, because gaps reference `metric_version` and evidence must remain reproducible.
- `quality_tests` run in CI as dbt tests and as golden tests against seeded data.
- `examples` are executable — they are the metric golden tests.
- A metric with no `owner` and no `quality_tests` cannot be certified, and only certified metrics
  are exposed to the product, the API and the AI layer.

### Initial metric set

`revenue`, `net_revenue`, `gross_margin`, `average_order_value`, `store_conversion`,
`website_conversion`, `app_install_to_activation`, `app_activation_to_first_purchase`,
`return_rate`, `footfall`, `transactions`, `stock_not_found_rate`, `unmet_request_rate`,
`within_promise_fulfilment_rate`, `median_service_wait`, `requests_per_staff_hour`,
`campaign_cost_per_acquired_customer`, `data_freshness`, `data_completeness`.

`data_freshness` and `data_completeness` are metrics like any other. Making them first-class is what
lets a data-quality gap suppress a business gap through the same machinery.

## 6. Data quality

`data_quality_flags` values are a closed enumeration: `late_arrival`, `out_of_range`,
`missing_required`, `type_coerced`, `duplicate_source_id`, `unknown_enum`, `future_dated`,
`negative_amount`, `currency_mismatch`, `schema_drift`.

A record that fails validation is quarantined with its source reference, failure list and mapping
version — never dropped. Silent rejection is prohibited: rejected counts appear in the connector run
summary, the admin data-quality view and the freshness/completeness metrics.
