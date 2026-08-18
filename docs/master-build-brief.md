# Claude Code Master Build Prompt

## FitOS Gap Intelligence Platform

Paste this prompt into Claude Code from the root of the existing `Git-Dann/FitOS` repository. Start Claude Code in Plan Mode.

```bash
cd FitOS
git checkout -b feat/gap-intelligence-platform
claude --permission-mode plan
```

Then paste everything below.

This document is a multi-session build contract. Claude Code must save a copy as `docs/master-build-brief.md` and use it as durable project context. Do not attempt the full platform in one context window. The first session is for audit and specification. Each implementation phase should run in a fresh named session with a checked-in handoff file.

---

# Mission

Take this repository from a browser prototype into a production-grade, multi-tenant data analysis platform with a working title of **FitOS Gap Intelligence**.

The product must connect fragmented business and operational data, convert it into governed metrics, identify evidence-backed gaps, quantify likely exposure as a range, assign action, and measure the result.

FitOS is one seed for the platform. Its fitting-room, stock-confidence, staff-capacity, fulfilment, missed-demand, customer, associate, manager and presenter concepts should inform the first product pack. Do not treat the current repository structure, local mock data or visual implementation as the production architecture.

The first complete pack is **Omnichannel Retail Operations**. It should connect money, audience, website, app-store, stock, service, staff and footfall signals for a fictional UK retailer. The platform must be designed so later packs can add other operating models without changing the core data contracts.

Do not build a generic BI dashboard, chart gallery, chat wrapper or connector marketplace with no decision model. The primary object is a **Gap**. The primary experience is a **Gap Ledger** that works like an operational issue system.

A Gap must answer:

1. What happened?
2. What was expected or compared?
3. How large is the difference?
4. What business exposure might it represent?
5. How reliable is that estimate?
6. Which source records and metric definitions support it?
7. What action is proposed?
8. Who owns the action?
9. What changed after the action?

The finished product must be demonstrable to frontline staff, managers, analysts, administrators and a presenter. It must include deterministic demo data, safe reset and purge controls, data mapping and cleansing, live-ready connector code, role-based access, audit history, source lineage, production tests and deployment documentation.

# Product thesis

Use this product statement as the anchor:

> FitOS turns fragmented operational data into a governed ledger of gaps, evidence and actions.

The platform has seven layers:

1. Connect sources.
2. Land raw data without mutation.
3. Map and clean data into canonical contracts.
4. Define governed metrics once.
5. Detect and rank gaps using deterministic rules and statistical methods.
6. Explain the evidence and propose actions.
7. Track action ownership and measured outcomes.

The product's defensible value is not connector count. It is the combination of cross-channel evidence, metric governance, gap logic, financial exposure ranges, confidence, source lineage and closed-loop action.

# First product pack

Build the first complete pack for an omnichannel fashion retailer with:

- 12 UK stores
- a commerce website
- iOS and Android apps
- paid and organic acquisition
- store footfall counters
- POS transactions and returns
- stock snapshots and stock checks
- staff rotas and service capacity
- fitting-room events based on the current FitOS prototype
- campaign records
- customer feedback and support signals

The pack must cover these gap families:

- Footfall to conversion
- Audience to purchase
- App acquisition to activation
- Demand to stock availability
- System stock to observed stock
- Staffing capacity to service demand
- Customer request to fulfilment
- Revenue to gross margin
- Campaign spend to attributable result
- Product trial to keep or return
- Data completeness, freshness and schema quality

Future packs should be possible through a documented pack contract. Example future packs include Digital Product Growth, Venue Operations and Studio Operations. Do not build those packs in this branch.

# Core domain model

## Gap

Implement a first-class `Gap` aggregate with at least these fields:

```text
id
organization_id
pack_key
gap_type
title
summary
scope_type
scope_id
metric_definition_id
metric_version
observed_value
expected_value
absolute_delta
percentage_delta
unit
currency
exposure_low
exposure_base
exposure_high
confidence_score
confidence_band
severity
status
owner_id
first_seen_at
last_seen_at
as_of_at
data_freshness_seconds
rule_id
rule_version
detector_run_id
assumptions
evidence_refs
recommended_actions
reason_codes
dedupe_key
created_at
updated_at
resolved_at
dismissed_at
outcome_id
```

Use a clear lifecycle:

```text
Detected -> Triaged -> Investigating -> Actioned -> Validating -> Resolved
                                      -> Dismissed
```

Every transition must be permission checked and written to an audit log.

## Exposure model

Never present a single precise financial value when the input data does not support that precision.

Store and display:

- low estimate
- base estimate
- high estimate
- formula
- assumptions
- source metrics
- confidence
- model version
- data freshness

Example:

```text
Unmet demand count x median item gross margin x recovery probability
```

The UI must label modelled values clearly. Do not make causal, savings or revenue claims without an experiment, a defined attribution method or direct observed evidence.

## Confidence model

Calculate confidence from explicit components:

- sample size
- completeness
- freshness
- source agreement
- metric stability
- detector fit
- identity-match quality where relevant

Keep the component scores in the evidence record. The AI layer may explain the score but may not set it.

## Evidence

A gap must link to immutable or versioned evidence references. Each evidence reference must contain:

```text
source_connection_id
source_record_locator
canonical_entity
canonical_record_id
metric_definition_id
metric_version
query_hash
query_parameters
observation_window
captured_at
sensitivity_classification
```

A user must be able to move from a gap to its metric definition, source connection, detector version and supporting records without guessing how a number was produced.

# Canonical data contracts

Define a base event envelope:

```text
event_id
organization_id
source_key
source_connection_id
source_record_id
source_schema_version
event_type
occurred_at
ingested_at
received_at
entity_type
entity_id
location_id
channel_id
product_id
campaign_id
anonymous_subject_id
amount
currency
quantity
properties
data_quality_flags
lineage_ref
```

Do not force all business data into one weak event table. Use the envelope for common lineage and routing, then create typed canonical facts and dimensions.

Required canonical facts:

- commerce transactions
- transaction lines
- returns and return lines
- footfall observations
- digital sessions and funnel events
- app-store performance observations
- inventory snapshots
- stock-check observations
- service requests and fulfilment events
- fitting-room sessions
- workforce shifts and capacity observations
- campaign spend and touchpoints
- feedback observations
- metric observations

Required dimensions:

- date and time
- organization
- source
- channel
- location
- product and variant
- campaign
- staff member or role
- anonymous customer or subject

Keep direct personal data out of the analytics store unless a documented use case requires it. Use pseudonymous identifiers and explicit sensitivity tags.

# Governed metric contract

Every product metric must be defined as code and version controlled. A metric definition must include:

```text
key
name
description
owner
grain
measure_expression
dimensions
allowed_filters
source_models
join_paths
unit
currency_policy
timezone_policy
null_policy
valid_from
valid_to
version
sensitivity
quality_tests
examples
```

The same metric definition must serve the product UI, exports, API and AI tools. Do not reimplement formulas in React components.

Required initial metrics include:

- revenue
- net revenue
- gross margin
- average order value
- store conversion
- website conversion
- app install to activation
- app activation to first purchase
- return rate
- footfall
- transactions
- stock not-found rate
- unmet request rate
- within-promise fulfilment rate
- median service wait
- requests per staff hour
- campaign cost per acquired customer
- data freshness
- data completeness

# Gap detector framework

Create a detector interface with versioned configuration, typed inputs, typed outputs, replay support and test fixtures.

Support these detector classes:

1. Static threshold
2. Ratio threshold
3. Baseline comparison
4. Peer or location comparison
5. Funnel drop
6. Seasonality-aware anomaly
7. Source mismatch
8. Data freshness
9. Data completeness
10. Schema drift
11. Repeated exception pattern
12. Financial leakage model

Each detector run must record:

- detector and rule version
- input metric versions
- query hash
- observation window
- thresholds
- output candidates
- suppressed candidates
- dedupe decisions
- run duration
- errors

Add a deduplication and correlation stage so related findings do not flood the ledger. One stock discrepancy pattern should become one evolving gap with a timeline, not dozens of near-identical rows.

AI must not be the primary detector. Use SQL, tested rules and statistical methods for detection and calculation. AI can summarise evidence, produce plain-language explanations, suggest investigation steps and help draft actions from governed inputs.

# Required product surfaces

## Shared shell

Create a dense, fast application shell with:

- compact left navigation
- consistent top bar
- saved views
- search
- command menu
- keyboard navigation
- list, board and timeline modes where useful
- right-side peek and detail inspector
- source freshness indicator
- organization and pack switcher
- role-aware navigation
- clear loading, stale, empty, partial and error states

## Routes

Build at least these routes:

```text
/inbox
/gaps
/gaps/[gapId]
/explore
/metrics
/metrics/[metricId]
/sources
/sources/[connectionId]
/playbooks
/outcomes
/frontline
/manager
/admin
/admin/connectors
/admin/mappings
/admin/data-quality
/admin/users
/admin/audit
/demo
/demo/presenter
/settings
```

## Gap Inbox

The inbox is the default signed-in view for managers, analysts and admins.

It should show compact rows with:

- gap type
- title
- scope
- exposure range
- confidence
- severity
- freshness
- owner
- status
- first and latest detection

Support keyboard movement with `J` and `K`, peek with `Space`, selection with `X`, command menu with `Cmd/Ctrl + K`, escape to close and bulk actions for assignment, status and dismissal.

## Gap detail

The detail view must contain:

- summary
- observed and expected values
- exposure range
- confidence breakdown
- evidence timeline
- source lineage
- metric definition and version
- assumptions
- detector explanation
- related gaps
- proposed actions
- owner and due date
- comments and activity
- outcome measurement
- audit history

The evidence panel must make it hard to mistake modelled data for observed data.

## Frontline view

The frontline view is an operating view, not an analytics dashboard. It must work well on a tablet and phone.

Show:

- current shift status
- next actions
- service pressure
- request queue
- stock exceptions
- assigned tasks
- promises at risk
- clear acknowledgement and completion controls

Keep business modelling and financial exposure out of this view unless the role has permission and a direct need.

## Manager view

Show:

- current operating pressure
- highest-value open gaps
- location and shift comparisons
- staff and service alignment
- demand and stock exceptions
- assigned actions
- outcomes from recent interventions

## Analyst view

Support:

- governed metric explorer
- cohort and segment comparisons
- gap replay
- detector configuration preview
- metric lineage
- data-quality inspection
- SQL or query details for authorised users
- saved analyses

## Admin view

Support:

- connectors and credentials
- sync schedules
- mapping versions
- schema drift
- quarantined records
- metric definitions
- detector rules
- roles and permissions
- retention policies
- audit records
- demo seed, reset and purge controls

## Presenter mode

Preserve the strongest part of the existing FitOS prototype: role-based storytelling.

Presenter mode must provide:

- scenario picker
- ordered steps
- customer, frontline, manager, analyst and admin views
- presenter notes
- role switching
- presentation mode with reduced chrome
- deterministic state
- reset before each story
- a visible distinction between observed, modelled and fictional demo data

# Design direction

Use Linear as an interaction reference, not as a visual clone.

Adopt these interaction principles:

- dense information with clear hierarchy
- keyboard-first operation
- command menu
- quick peek without losing list context
- consistent view controls
- strong list interactions
- side detail panels
- calm motion
- dimmer navigation than the work surface
- predictable focus states
- fast optimistic interactions with visible recovery on failure

Do not copy Linear's branding, exact colours, icons, spacing or layouts.

Before coding the main shell, produce three distinct design concepts in `docs/design-concepts.md`:

1. **Gap Ledger**: compact operational issue list with evidence peek.
2. **Operations Radar**: live signals grouped by location, channel and time.
3. **Evidence Workbench**: split view joining gaps, metrics and source records.

For each concept, include:

- text wireframes for desktop and tablet
- primary workflows
- information hierarchy
- keyboard model
- advantages
- risks
- fit by role

Score the concepts against speed, clarity, data density, frontline usability, analyst depth, demo value and implementation risk. Select or combine the strongest direction. Do not implement the first concept simply because it was written first.

## Visual rules

Use a restrained neutral system with one product accent and semantic status colours. Build a token system for colour, spacing, typography, radius, shadow, borders, motion and chart marks.

Prefer:

- compact rows
- clear typographic hierarchy
- tabular numerals
- thin borders
- restrained shadows
- 6px to 10px radii
- useful whitespace rather than oversized empty areas
- integrated charts inside analytical views
- small multiples
- confidence bands
- target and baseline markers
- annotations tied to evidence

Avoid:

- purple-blue gradients
- glass panels
- glowing borders
- giant metric cards
- a home screen centred on chat
- decorative sparkles
- rounded cards for every piece of content
- pill controls everywhere
- oversized headlines inside the signed-in product
- random gradient blobs
- fake live activity
- generic AI copy
- charts with no scale, source, comparison or as-of time
- loading skeletons that do not match the final layout

Use Motion for React only where movement explains state or preserves spatial context. Default interaction duration should usually sit between 120ms and 220ms. Honour reduced-motion preferences. Replace large transform animations with opacity changes for reduced-motion users.

Build light and dark themes from tokens. Test legibility, focus, hover, selected, disabled, warning and error states in each theme.

Use a custom component system built from Radix primitives and project tokens. Do not paste a default shadcn interface and stop. A third-party primitive may provide behaviour, but FitOS must own the visual language.

# Recommended technical architecture

Create a monorepo with `pnpm` and Turborepo.

Use this structure as the target, adjusting only after a written architecture decision:

```text
apps/
  web/                  Next.js product application
  storybook/            component and data-visualisation workshop
services/
  api/                  FastAPI control and product API
  worker/               Temporal workers, ingestion and detectors
  semantic/             Cube Core semantic layer
packages/
  ui/                   tokens, primitives and product components
  contracts/            generated TypeScript contracts and shared schemas
  charts/                reusable evidence-led visualisations
  demo/                 deterministic fixtures and scenario definitions
  config/               shared lint, TypeScript and test settings
connectors/
  sdk/
  csv_upload/
  rest_openapi/
  webhook/
  stripe/
  shopify/
  ga4/
  app_store_connect/
  google_play/
  retail_templates/
data/
  dbt/
  seeds/
  contracts/
infra/
  compose/
  opentofu/
  scripts/
docs/
legacy/
  fitos-prototype/
```

Preserve the current prototype and screenshots under `legacy/fitos-prototype` before replacing its runtime. Keep git history intact with `git mv` where practical.

## Web application

Use:

- current stable Next.js App Router
- current stable React
- strict TypeScript
- Tailwind CSS with project tokens
- Radix primitives
- Motion for React
- TanStack Query
- TanStack Table and Virtual
- React Hook Form with Zod
- Visx and D3 scale utilities for custom charts
- a generated OpenAPI client
- Storybook
- Playwright
- axe accessibility checks

Use Server Components for server-rendered read surfaces where they reduce client work. Use client components for interaction-heavy tables, inspectors and charts. Keep state in the URL for filters, time windows, grouping and selected views where practical.

Do not place large CSS strings inside React components. Do not hard-code metric values in UI files.

## API and data services

Use:

- FastAPI
- Pydantic v2
- SQLAlchemy 2 or SQLModel only if its limits are acceptable
- Alembic migrations
- typed OpenAPI contracts
- structured problem responses
- cursor pagination
- idempotency keys for write and ingest endpoints
- Server-Sent Events for connector and detector progress

Use Python for connectors, data contracts, statistics, cleansing and detector code. Keep product and control APIs in one service until measured load or team ownership provides a clear reason to split them.

## Control plane

Use PostgreSQL for:

- organizations
- memberships and roles
- source definitions and connections
- encrypted credential references
- connector runs and checkpoints
- schema and mapping versions
- metric metadata
- detector rules
- gap lifecycle
- actions and outcomes
- comments
- audit history
- retention settings
- demo snapshots

Use PostgreSQL row-level security for organization-scoped control-plane records in addition to service-layer checks. Add automated cross-tenant access tests.

## Analytics plane

Use ClickHouse for canonical facts, dimensions, metric observations, detector inputs and aggregate tables.

Use:

- partitioning by organization and date where appropriate
- ordering keys based on actual query patterns
- incremental materialized views for common aggregates
- projections only after profiling
- explicit retention and tiering policies
- query limits and timeouts
- organization filters injected by the governed query layer

Do not send unrestricted user-written SQL directly from the browser to ClickHouse.

## Raw storage

Use S3-compatible object storage for immutable raw payloads, import files, connector response snapshots, rejected records and Parquet exports.

Use MinIO locally. Support S3 or Cloudflare R2 in hosted environments through a storage adapter.

Raw records must be immutable. Corrections happen in mappings, transformations and canonical versions, not by silently changing the source copy.

## Ingestion

Use `dlt` for REST extraction, pagination, authentication, incremental state, merge and schema handling. Wrap it behind the project connector SDK so product code does not depend on dlt-specific objects.

Use Temporal for durable connector runs, backfills, cleansing jobs, detector runs, retries, schedules, cancellation and progress reporting.

Every external call must have:

- bounded retries
- exponential backoff with jitter
- rate-limit handling
- timeout
- idempotency strategy
- checkpointing
- structured errors
- trace context

## Transformation and semantic layer

Use dbt Core with the ClickHouse adapter for canonical transformations, data tests and documented models.

Use Cube Core as the governed semantic layer for measures, dimensions, joins, access policies, pre-aggregations and serving APIs. Expose only certified metrics and authorised dimensions to product and AI consumers.

If a current compatibility issue makes this combination unsafe, write an ADR with benchmarks and select the smallest replacement that keeps metric definitions governed and reusable.

## Authentication and authorisation

Use Better Auth for the first production implementation with:

- organization support
- role and permission definitions
- secure session cookies
- JWT and JWKS support for the Python API
- local demo identities
- invitation flow
- passwordless or social login only after the base flow is tested

Design an auth-provider boundary so enterprise SSO through WorkOS can be added later without rewriting product permissions.

Initial roles:

```text
frontline
manager
analyst
admin
owner
presenter-demo
```

Define permissions as capabilities, not role-name checks scattered through components.

## Observability

Instrument the web, API, worker, connector and detector paths with OpenTelemetry traces, metrics and structured logs.

Propagate trace context from a UI action through API, Temporal workflow, connector call, transformation and detector run. Include organization and run identifiers, but no direct personal data or secrets.

Provide local dashboards or documented exports for:

- API latency and error rate
- connector run health
- records processed and rejected
- workflow retries
- ClickHouse query duration
- detector duration and output count
- gap creation and dedupe
- demo reset runs

## Infrastructure

Provide:

- Docker Compose local environment
- one command to install and start all dependencies
- production Dockerfiles
- OpenTofu modules or a clear provider-neutral deployment layer
- separate local, preview, staging and production configuration
- database migration jobs
- backup and restore runbooks
- health and readiness probes
- zero-downtime-compatible schema changes

Use managed PostgreSQL, ClickHouse, object storage and Temporal for the initial hosted reference architecture. Keep service containers portable.

# Connector SDK

Create a capability-based connector contract. A connector manifest should describe:

```text
key
name
category
version
auth_type
supported_resources
supports_backfill
supports_incremental
supports_webhooks
supports_schema_inspection
rate_limit_model
required_secrets
optional_settings
canonical_targets
```

A connector implementation must provide typed methods for:

- configuration validation
- credential test
- schema and resource listing
- backfill planning
- incremental extraction
- webhook verification and parsing where supported
- source-to-staging mapping
- health reporting
- checkpoint export and restore
- fixture replay

## Required connector tiers

### Tier 1: complete and fully testable locally

- CSV and XLSX upload
- generic REST and OpenAPI connector
- generic signed webhook collector
- Stripe
- retail POS CSV template
- footfall CSV and webhook template

### Tier 2: production-ready code with recorded fixtures and credential-driven live mode

- Shopify
- Google Analytics 4 Data API
- Apple App Store Connect
- Google Play developer reporting and sales data

No connector card may pretend to be connected. The UI must show one of: configured, testing, syncing, healthy, delayed, schema changed, failed, disabled or fixture mode.

Use official APIs where an official API exists. Do not use scraping as the default integration method. Any later public-web collector must respect access rules, rate limits and provenance.

# Mapping and cleansing workspace

Build a mapping workflow that lets an admin:

1. Preview source records.
2. Select a canonical target.
3. Map source fields to canonical fields.
4. Set date, timezone, locale and currency handling.
5. Define primary and dedupe keys.
6. Apply typed transformations.
7. Preview valid, invalid, duplicate and quarantined counts.
8. Save a versioned mapping.
9. Run a backfill against the version.
10. Compare versions.
11. Roll back to an earlier version.

Required transformations:

- trim and normalise strings
- parse dates and timestamps
- timezone conversion
- currency minor-unit conversion
- numeric parsing
- enum mapping
- null and blank handling
- boolean parsing
- identifier normalisation
- field concatenation and splitting
- hash or pseudonymise selected values

All transformations must be deterministic, previewable and recorded. No AI transformation may run silently. AI can suggest a mapping, but the admin must review the proposed changes and see sample outputs before saving.

Quarantined records must keep their source reference, validation failures and mapping version. Support reprocessing after a mapping correction.

# Demo dataset

Create a deterministic fictional tenant called **Northstar Outfitters**.

Seed 90 days of coherent data across all supported channels. Target roughly 750,000 to 1,500,000 canonical records so the system behaves like a real product without making local setup impractical.

Use a fixed seed and stable identifiers. The same seed must produce the same record counts, gap IDs, scenario outputs and screenshots.

Seed these scenarios:

## Scenario 1: Saturday capacity leak

- footfall rises
- fitting-room demand rises
- frontline capacity stays flat
- service waits rise
- store conversion falls
- a modelled gross-margin exposure range is generated

## Scenario 2: Stock truth gap

- system stock shows units available
- repeated staff stock checks fail
- customer requests remain unmet
- alternatives are partly accepted
- one evolving stock gap is created with linked FitOS service evidence

## Scenario 3: App acquisition leak

- app installs rise after a campaign
- activation falls on one app version
- first purchase falls
- review sentiment and crash-related support messages rise
- the finding links app-store, product and commerce evidence

## Scenario 4: Campaign and store mismatch

- digital audience rises in selected regions
- website engagement improves
- store visits do not rise as expected
- attribution confidence is limited and labelled
- the proposed action is an investigation or controlled test, not a causal claim

## Scenario 5: Return margin leak

- one product variant sells well
- its return rate and handling cost rise
- revenue looks healthy while gross margin weakens
- the gap ranks by margin exposure rather than revenue alone

## Scenario 6: Data-quality fault

- one footfall source stops reporting
- one connector changes a field type
- freshness and completeness gaps appear
- business gaps affected by the missing data show lower confidence

Seed demo users for each role. Add a safe local-only role switcher and a guided presenter route. Do not commit reusable passwords. Use development-only auth seeding or magic links.

# Demo reset, cleanse and purge

Provide CLI commands and admin UI controls for:

```bash
pnpm demo:seed
pnpm demo:reset
pnpm demo:snapshot
pnpm demo:purge
pnpm demo:verify
```

The commands may call Python scripts behind the scenes.

Rules:

- seed is idempotent
- reset restores the named demo tenant to its original snapshot
- purge deletes only the named demo tenant
- each command supports dry-run
- destructive actions require the exact tenant slug
- production mode blocks fixture seeding by default
- no command may run against all organizations without a separate break-glass path
- every reset or purge writes an audit record
- a failed reset rolls back or restores the last valid snapshot
- verification checks deterministic counts and expected gap outputs

The admin UI must explain what each action will remove. Require typed confirmation for purge. Show progress, result counts and failures.

# AI and MCP layer

AI is a supporting layer, not the source of numeric truth.

Build an evidence assistant that can:

- explain a gap in plain English
- summarise supporting evidence
- state assumptions and confidence limits
- suggest investigation steps
- draft an action plan
- compare related gaps
- produce a manager summary

It must operate on a structured evidence bundle created by the API and semantic layer. It must not receive unrestricted database access and must not invent metric values.

Every answer must cite internal metric, gap and evidence identifiers that the UI can open.

Add an MCP server for FitOS with read-first tools such as:

```text
list_metrics
get_metric_definition
query_certified_metric
list_gaps
get_gap
get_gap_evidence
list_source_health
```

Write actions such as assignment or status changes must be separate tools with explicit permissions and confirmation.

Make the MCP interface tenant aware. Apply the same semantic and permission policies used by the product API.

Add evaluation fixtures for:

- correct numeric citation
- refusal to claim causation from correlation
- confidence and assumption disclosure
- tenant isolation
- prompt injection inside source text
- unsupported question handling

Follow OWASP AISVS checks for the AI-enabled surface and OWASP ASVS Level 2 as the base application-security target.

# API requirements

Create versioned endpoints under `/v1`.

Required resource groups:

```text
/auth
/organizations
/sources
/connections
/connector-runs
/imports
/mappings
/quarantine
/metrics
/metric-observations
/detectors
/detector-runs
/gaps
/gap-actions
/outcomes
/comments
/audit
/demo
/health
```

Use:

- cursor pagination
- stable error codes
- RFC 9457-style problem responses
- idempotency keys
- ETags or version checks for concurrent edits
- explicit organisation context
- rate limiting
- request IDs
- trace IDs
- UTC storage with organisation display timezone
- ISO currency codes and integer minor units for money

Generate the TypeScript API client. Do not hand-maintain duplicate request types.

# Security and privacy

Create `docs/threat-model.md` before exposing connectors or data APIs.

Cover:

- tenant boundary failure
- IDOR
- connector credential theft
- webhook forgery
- CSV formula injection
- SQL injection
- SSRF through generic REST connectors
- prompt injection in imported text
- malicious files
- unsafe deserialisation
- data exfiltration through exports or AI tools
- destructive reset misuse
- audit tampering
- dependency compromise

Required controls:

- server-side permission checks
- PostgreSQL row-level security
- semantic-layer tenant policies
- encrypted credential values or secret-manager references
- secret redaction in logs and errors
- signed webhook validation
- outbound host allowlists and private-network blocking for generic REST connections
- file type, size and content validation
- CSV formula escaping on exports
- malware scanning adapter for uploads
- CSRF protection
- secure cookie settings
- Content Security Policy
- rate limits
- immutable audit events
- data retention and deletion jobs
- dependency and secret scanning in CI
- software bill of materials generation

Add negative tests for each major tenant and permission boundary.

# Accessibility

Target WCAG 2.2 AA.

Test:

- full keyboard operation
- visible focus
- screen-reader names and structure
- table and chart summaries
- non-colour status cues
- reduced motion
- zoom and text reflow
- mobile touch targets
- error association
- live-region use for background progress

For every chart, provide an accessible summary and a data table or export path.

# Performance and reliability targets

For the seeded demo dataset on a normal local development machine:

- gap inbox API p95 under 750ms after warm-up
- common metric query p95 under 1 second after warm-up
- first signed-in shell usable within 2.5 seconds on a representative broadband profile
- row interactions remain responsive with 10,000 listed gaps through pagination and virtualisation
- connector reruns are idempotent
- worker restarts do not lose workflow progress
- duplicate webhooks do not create duplicate canonical facts
- partial connector failure does not roll back successful independent resources

Profile before adding caches. Record query plans and benchmarks for the main views.

# Testing strategy

Use a testing pyramid and data-contract tests.

## TypeScript

- Vitest unit tests
- React Testing Library for component behaviour
- Playwright for end-to-end and visual tests
- axe checks in Playwright

## Python

- pytest
- Hypothesis for exposure and detector invariants
- connector contract tests
- mapping and cleansing tests
- Temporal workflow tests
- API integration tests

## Data

- dbt schema and data tests
- canonical contract tests
- metric golden tests
- detector golden fixtures
- seed determinism test
- data-quality fault tests
- ClickHouse migration and materialized-view tests

## Required end-to-end test

Prove this full path:

1. A source record enters through a connector or upload.
2. Raw data lands in object storage.
3. A mapping creates canonical records.
4. dbt builds the governed model.
5. the semantic layer returns a certified metric.
6. a detector creates or updates a gap.
7. the gap appears in the inbox.
8. a manager opens evidence and assigns an action.
9. an outcome record changes the gap state.
10. the demo reset returns the tenant to its original state.

## Visual review

For each major route, capture screenshots at:

- 1440 x 900
- 1024 x 768
- 390 x 844

Use a design-review subagent to compare the captures against the design rules. Fix issues before marking a route complete.

Test empty, loading, delayed, partial, error, unauthorised and offline-recovery states. A successful happy path alone is not completion.

# Claude Code operating method

Follow this method for the whole build.

## 1. Audit before coding

Inspect:

- repository tree
- git history
- current routes
- data types
- rule engine
- tests
- build scripts
- screenshots
- product copy
- known limitations

Write `docs/repo-audit.md` with:

- product concepts worth preserving
- code worth reusing
- code that should be replaced
- data and security gaps
- design strengths and weaknesses
- migration risks
- proposed repository migration

Do not make production claims about code you have not run.

## 2. Write the specification set

Before implementation, create:

```text
docs/product-spec.md
docs/design-concepts.md
docs/design-system.md
docs/architecture.md
docs/data-contracts.md
docs/gap-model.md
docs/connector-sdk.md
docs/security-and-privacy.md
docs/threat-model.md
docs/demo-plan.md
docs/implementation-plan.md
```

Create ADRs for major decisions, including:

- monorepo structure
- analytics store
- workflow engine
- semantic layer
- auth provider
- raw storage
- AI boundary

In the first session, review the documents for contradictions, create the phase plan, commit the specification set and stop. Planning alone is not completion of the project. Start implementation in a fresh session using the continuation prompt defined below.

## Session protocol

Treat this as a sequence of bounded Claude Code sessions, not one long conversation.

Create and maintain `docs/build-state.md` with:

```text
current_phase
status
completed_outcomes
changed_files
commands_run
test_results
decisions_and_adrs
open_risks
next_phase
next_session_prompt
```

Rules:

- Session 1 covers repository audit, product specification, design concepts, architecture, threat model and implementation plan.
- Start each implementation phase in a fresh named session.
- Read only the master brief, build state, relevant ADRs and files needed for that phase.
- Use subagents for broad study so the main context remains focused.
- Run `/clear` between unrelated phases.
- Use `/compact` only to retain decisions inside one related phase.
- End each session by updating `docs/build-state.md`, running phase checks, committing coherent work and printing the exact next-session prompt.
- Do not leave a phase marked complete when its acceptance tests fail.

Use this continuation prompt for Session 2 and later, replacing the phase name:

```text
Read @docs/master-build-brief.md, @docs/build-state.md, @docs/implementation-plan.md, @CLAUDE.md and the ADRs relevant to the next incomplete phase. Start in Plan Mode. Confirm the bounded phase outcome, inspect only the related code, then implement the phase end to end. Run the required tests and visual checks, ask the verification subagent to challenge the result, fix its findings, update docs/build-state.md, commit the coherent outcome and print the exact prompt for the next fresh session. Do not start a later phase until this phase passes its acceptance checks.
```

## 3. Configure Claude Code for this repository

Create a concise root `CLAUDE.md` containing only durable repository instructions:

- build, lint, typecheck and test commands
- architecture boundaries
- rules for tenant scoping
- no hard-coded metrics
- no secrets
- migration and destructive-command rules
- visual verification requirement
- commit conventions

Create focused subagents in `.claude/agents/`:

```text
repo-auditor.md
data-architect.md
design-reviewer.md
security-reviewer.md
verification-engineer.md
```

Create reusable skills in `.claude/skills/`:

```text
add-connector/SKILL.md
add-gap-detector/SKILL.md
run-demo-reset/SKILL.md
visual-qa/SKILL.md
```

Use documented Claude Code hooks for deterministic checks. At minimum:

- block writes to real `.env` and secret files
- block destructive database commands outside the documented demo path
- format touched code
- run targeted lint and type checks after related edits
- run a stop verification command before claiming completion

Keep hooks fast and scoped. Run the full suite in CI and before final completion.

Use subagents for repository study, data architecture, security review and final verification so the main context stays focused. Use isolated git worktrees for independently mergeable tasks only. No two agents may edit the same files in parallel.

## 4. Build one complete vertical slice first

Before adding broad connector coverage, complete this path with demo data:

```text
seed -> raw object -> ingest -> map -> canonical fact -> governed metric -> gap -> evidence -> action -> outcome -> reset
```

The vertical slice should use the Stock Truth Gap scenario because it carries the strongest concepts from the current FitOS prototype.

Do not build five empty sections before one section works end to end.

## 5. Implement in bounded phases

### Phase A: repository and local platform

- create the monorepo
- preserve legacy reference
- add Docker Compose
- add local one-command startup
- add CI skeleton
- add root commands
- add health checks

### Phase B: auth and tenancy

- organizations
- memberships
- roles and permissions
- API token verification
- row-level security
- audit base
- cross-tenant tests

### Phase C: data plane

- raw object storage
- connector SDK
- upload and REST connectors
- Temporal workflows
- mapping and quarantine
- canonical ClickHouse models
- dbt tests

### Phase D: semantic and gap engine

- governed metrics
- Cube policies
- detector framework
- exposure and confidence models
- gap lifecycle
- evidence lineage

### Phase E: product UX

- design system
- app shell
- gap inbox
- gap detail
- metrics and sources
- frontline, manager, analyst and admin routes
- responsive and accessible states

### Phase F: demo and presenter

- Northstar dataset
- seeded scenarios
- role switcher
- presenter flow
- reset, purge and verification
- demo guide

### Phase G: integrations

- Tier 1 completion
- Tier 2 adapter code and fixtures
- connector health UI
- schema drift
- reauth and retry flows

### Phase H: AI and MCP

- structured evidence bundle
- explanation assistant
- evaluation fixtures
- read-first MCP server
- permissioned write tools

### Phase I: hardening

- performance profiling
- threat-model review
- ASVS and AISVS checklists
- production images
- OpenTofu reference
- backup and restore test
- final visual review

Commit after each coherent vertical outcome with a descriptive message. Keep the branch buildable.

## 6. Verify each phase

For each phase:

1. Run targeted tests while editing.
2. Run lint and type checks.
3. Run the relevant integration path.
4. Capture UI screenshots where applicable.
5. Ask the verification subagent to challenge the result.
6. Fix the findings.
7. Commit only after checks pass.

Do not claim success from code inspection alone. Show command output, test results, record counts, API examples or screenshots.

# Repository commands

Create a clear root command set. The final names may differ slightly, but the repository must provide equivalents for:

```bash
pnpm install
pnpm dev
pnpm dev:infra
pnpm build
pnpm lint
pnpm typecheck
pnpm test
pnpm test:unit
pnpm test:integration
pnpm test:e2e
pnpm test:visual
pnpm test:data
pnpm verify
pnpm demo:seed
pnpm demo:reset
pnpm demo:purge
pnpm demo:verify
```

Python dependencies should use `uv` with a locked dependency file. JavaScript dependencies should use a committed `pnpm-lock.yaml`.

# CI requirements

Build GitHub Actions workflows for:

- formatting and lint
- TypeScript type checks
- Python type checks
- unit tests
- API and connector integration tests
- dbt tests
- ClickHouse migration tests
- Playwright end-to-end tests
- accessibility checks
- visual regression on approved baselines
- dependency audit
- secret scan
- container scan
- SBOM generation
- production build

Use service containers or a reusable Compose setup for integration jobs. Cache dependencies, not test results that could hide failures.

# Documentation requirements

Update the root README so a new engineer can:

1. understand the product
2. install dependencies
3. start local infrastructure
4. seed the demo
5. sign in as each role
6. run verification
7. add a connector
8. add a detector
9. reset the demo
10. inspect traces and logs

Also create:

```text
docs/local-development.md
docs/deployment.md
docs/runbooks/connector-failure.md
docs/runbooks/schema-drift.md
docs/runbooks/demo-reset.md
docs/runbooks/backup-restore.md
docs/data-dictionary.md
docs/demo-guide.md
docs/accessibility.md
docs/security-checklist.md
```

# Non-negotiable product rules

- No hard-coded analytical values in React components.
- No metric formula duplicated across UI and API.
- No gap without a metric version, detector version, evidence and as-of time.
- No modelled financial value without low, base, high, assumptions and confidence.
- No AI-generated number accepted as a metric result.
- No connector secret stored in plaintext application tables.
- No tenant-scoped query without tested tenant context.
- No destructive demo action that can target non-demo tenants by accident.
- No fake connector status.
- No placeholder buttons in a route marked complete.
- No first-draft design shipped without alternative concepts and screenshot review.
- No generic AI visual treatment.
- No large component containing unrelated product, data and styling logic.
- No silent schema drift.
- No silent record rejection.
- No causal claim from simple correlation.
- No completion claim without verification evidence.

# Definition of done

The branch is complete only when all of these are true:

1. A new developer can start the full local product from documented commands.
2. The current FitOS product concepts are preserved in the retail service model and presenter stories.
3. Northstar Outfitters seeds deterministically.
4. At least one source can be uploaded and mapped through the UI.
5. The generic REST connector can complete an incremental fixture sync.
6. Stripe can run in fixture mode and has a credential-driven live path.
7. Tier 2 connector code passes contract tests with recorded fixtures.
8. Raw, canonical and governed layers are visibly separate.
9. Certified metrics come from the semantic layer.
10. All six seeded scenarios create the expected gaps.
11. A gap contains exposure range, confidence, assumptions, freshness and evidence.
12. A manager can assign an action and record an outcome.
13. Frontline, manager, analyst, admin and presenter experiences work.
14. The demo can reset safely from CLI and UI.
15. Cross-tenant tests pass.
16. Connector idempotency and duplicate-webhook tests pass.
17. Accessibility tests pass for the main routes.
18. Desktop, tablet and mobile screenshots have been reviewed and corrected.
19. The production build passes.
20. CI is green.
21. The final security review has no unresolved high-severity issue.
22. The final report lists remaining medium and low risks honestly.

# Final response format

When implementation is complete, respond with:

1. Product summary
2. Architecture delivered
3. Major repository changes
4. Demo users and exact demo steps
5. Connector status by connector
6. Seeded scenario results
7. Data reset and purge commands
8. Test and build evidence
9. Screenshot locations
10. Security review result
11. Performance results
12. Known limitations and next priorities
13. Commit list
14. Exact commands to run locally

Do not say the work is production-ready unless the production checks above have run and the remaining limitations are stated.

Begin Session 1 now in Plan Mode. Audit the repository, save this contract to `docs/master-build-brief.md`, create the specification set, review it for contradictions, create `docs/build-state.md`, commit the planning work and finish with the exact Session 2 prompt for the first vertical slice.
