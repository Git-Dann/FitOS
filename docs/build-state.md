# Build state

Updated at the end of every session. Read this before starting a phase.

---

## current_phase

Phase C — data plane.

## status

**Acceptance checks pass. All seven Phase C criteria are met and each is proven by execution.**

422 Python tests pass across the API, worker, connectors and canonical layers, plus 19 dbt models
and tests. `pnpm verify` exits 0 and now includes `test:data`, which used to be a placeholder that
exited 0 without running anything.

Every criterion is checked against a real dependency rather than a mock: PostgreSQL for tenancy,
ClickHouse for the canonical contract and the governed models, Temporal for the workflows, and a
real Better Auth instance for the JWKS contract carried over from Phase B. Four new CI jobs carry
those services with `FITOS_REQUIRE_*` flags, so a missing dependency fails rather than reads as a
passing check.

Phases A and B remain complete; their records are below.

## acceptance

| # | Criterion | Evidence |
| --- | --- | --- |
| 1 | The 14-point connector contract suite passes for both connectors | `contract_tests.py`, inherited by both. 43 CSV + 54 REST tests |
| 2 | Idempotency: the same extract twice yields the same canonical row count | Proven three times — identical record *ids* per connector, identical staging rows per run, and a re-ingested row collapsing to one under `FINAL` in ClickHouse |
| 3 | Duplicate webhook: the same signed delivery twice yields one canonical fact | `test_the_same_delivery_twice_is_accepted_once`, over HTTP, with the row count asserted |
| 4 | SSRF: private, loopback, link-local and redirect-to-private all refused | 38 egress tests plus connector-level refusals. Release gate |
| 5 | A mapping version can be created, previewed, backfilled, compared and rolled back through the API | `test_mappings.py` (25) and `test_runs.py` (14) |
| 6 | A malformed record is quarantined with its reason and mapping version, the run completes, counts are never silent | `test_runner.py`, including `read == written + quarantined` for every fixture |
| 7 | dbt tests pass; canonical contract tests pass | 19 dbt, 53 canonical, 6 governed-model — all against live ClickHouse |
| 8 | Worker restart mid-backfill resumes from checkpoint without duplicating rows | `test_a_restart_resumes_from_the_checkpoint_without_duplicating` |
| 9 | Threat-model review for the ingestion boundary recorded | [threat-model-review-phase-c.md](threat-model-review-phase-c.md) — and it found two gaps |

## completed_outcomes

1. **The egress boundary, built before anything that depends on it.** A connector cannot construct
   an HTTP client; it gets one with the policy fastened to it, and the contract suite reads each
   connector's source to prove there is no second client. Connections go to an address that was
   actually checked, which closes the DNS rebind.
2. **A contract, not a template.** The 14 points ship as library code that a connector inherits by
   subclassing. A contract each connector reimplements is not a contract. Several checks exist to
   stop their partner passing vacuously — the "rejects bad config" test has a "accepts good config"
   twin, and so does quarantine.
3. **Idempotency from content, not bookkeeping.** Record ids derive from the source's own id or from
   a digest; raw keys are the content digest; the canonical layer is `ReplacingMergeTree` on the
   natural key. Every link in that chain has a test, because the chain fails silently if any one of
   them breaks.
4. **Mapping versions that make corrections a forward operation.** An applied version is frozen
   except for `is_active`; rolling back re-applies an earlier version rather than deleting a later
   one; a backfill re-reads history through the currently active mapping. Nothing edits a canonical
   row in place.
5. **Nothing is dropped silently.** Quarantine carries a closed enumeration of reasons, the raw
   reference and the mapping version. The run summary always states the rejected count, including
   when it is zero.
6. **Deterministic workflows, enforced statically.** An AST check fails on wall-clock time,
   randomness, I/O or a retry loop in a workflow body, and it was verified by introducing a
   violation and watching it fail.
7. **A governed layer whose correctness is tested, not assumed.** The Stock Truth model is checked
   against three snapshots around one count, where the plausible mistake — nearest snapshot in
   absolute time — would raise a gap against somebody who counted correctly.
8. **An ingestion boundary that treats its input as hostile.** Sniffed contents, caps applied while
   reading, filenames never used to build paths, and one indistinguishable refusal for every
   webhook failure.

## changed_files

```text
connectors/      sdk/ — egress, http, types, context, raw_store, quarantine, webhooks,
                 mapping, contract_tests (the 14 points as library code)
                 csv_upload/ · rest/ — the two Tier 1 connectors
services/api     models.py (+Connection, MappingVersion, ConnectorRun, QuarantinedRecord,
                 WebhookDelivery) · migrations 0005 · routes/{mappings,ingest,runs}.py
services/worker  runner.py (the run executor) · workflows.py (Temporal)
data/            canonical/ — schema.py, apply.py and the contract tests
                 dbt/ — three governed models, 16 dbt tests
docs/            threat-model-review-phase-c.md · threat-model.md cross-reference
.github/         workflows/ci.yml — canonical and workflows jobs
```

## commands_run

PostgreSQL 16.13 on 5433, plus the full Compose stack for ClickHouse, Temporal, MinIO and Cube.

| Command | Result |
| --- | --- |
| `pnpm verify` | **exit 0** — now includes `test:data` |
| `uv run pytest` | **422 passed, 6 skipped** |
| `pnpm canonical:apply` | applied 12 canonical tables |
| `dbt build` | **PASS=19** — 3 models, 16 tests |
| `dbt build` against an empty database | **ERROR=3** — reproduces the CI failure the apply step fixes |
| `dbt test` with a seeded negative amount | **FAIL 1** — "Got 1 result, configured to fail if != 0" |
| Determinism check with `uuid.uuid4()` in a workflow body | fails, naming the call and the fix |
| `pnpm dev:infra` | 7/7 healthy in 18s |

## test_results

422 Python tests plus 19 dbt models and tests. The largest suites:

| File | Tests | Covers |
| --- | --- | --- |
| `test_rest_connector.py` | 54 | The 14 points, egress, webhooks, pagination, secrets |
| `test_canonical_schema.py` | 53 | ClickHouse physical rules, checked against the server |
| `test_csv_connector.py` | 43 | The 14 points, plus what spreadsheets actually send |
| `test_egress.py` | 38 | One test per SSRF bypass |
| `test_ingest.py` | 26 | Uploads and signed webhooks over HTTP |
| `test_mappings.py` | 25 | Create, preview, apply, compare, roll back |
| `test_workflows.py` | 17 | Determinism statically, behaviour against real Temporal |
| `test_runner.py` | 17 | Idempotency, quarantine, partial results, resumption |
| `test_runs.py` | 14 | Runs and backfills through the API |
| `test_governed_models.py` | 6 | The governed models against seeded data |

The ones worth naming:

- `test_the_stock_check_compares_against_the_snapshot_before_it` — three snapshots around one count,
  where the plausible mistake reports a discrepancy of −28 against somebody who counted correctly.
- `test_the_checkpoint_is_saved_after_the_batch_not_before` — watches the call order, because the
  other order loses records and nothing reports it.
- `test_the_client_exposes_no_unchecked_way_to_make_a_request` — asserts the egress client's public
  surface is exactly six names, so inheritance cannot quietly add a seventh.
- `test_a_transport_error_does_not_leak_the_api_key` — the leak that actually happens, which is
  never `log(api_key)`.
- `test_read_always_equals_written_plus_quarantined` — a record that is read and neither written nor
  quarantined has vanished, and no count would ever show it.

## decisions_and_adrs

No new ADRs. Phase C implements the decisions in ADRs 0002 (ClickHouse), 0003 (Temporal), 0004
(Cube) and 0006 (raw storage). Five implementation choices worth recording:

1. **The 14-point contract ships as library code.** A contract each connector reimplements is not a
   contract. It is capability-aware without being lenient: a connector declaring no webhook support
   skips those tests but is still checked for *refusing* one, because an endpoint that accepts
   unverified payloads is worse than no endpoint.
2. **Transforms are a closed set of eight, not an expression language.** An expression language
   configured by whoever can edit a connection is remote code execution, and "it is only a formula"
   is how that ships.
3. **The mapping interpreter lives in the SDK, not in either service.** Both need it and neither
   owns it: the API previews and compares, the worker applies. A preview computed by different code
   from the run it predicts lies at the worst possible moment.
4. **A backfill fans out one child workflow per window.** A failure costs one window, the plan stays
   deterministic so a resumed backfill knows what is done, and a year-long range does not accumulate
   one enormous history.
5. **Canonical schema creation is a deployment step, not a test fixture.** Discovered the hard way —
   see below.

## bugs_found_by_running_it

Phase B found four. Phase C found seven more, and every one of them reads as correct code.

1. **`join_use_nulls` in the Stock Truth model.** ClickHouse fills an unmatched LEFT JOIN row with
   type *defaults*, not NULL, so a variant the inventory feed has never covered came back as "the
   system believed 0 units, at 1970-01-01" — a plausible-looking row reporting a phantom surplus
   equal to whatever was counted. And the setting has to be written into the query: a dbt model
   config applies when the view is *created*, and a view runs its query later.
2. **The canonical schema was created by a pytest fixture.** So the tables existed as a side effect
   of running tests. Fine locally, fatal on a fresh CI server the moment `dbt build` ran first —
   which it did. Now an explicit applier that CI runs before dbt and the tests call directly.
3. **`sources.yml` hard-coded the schema**, so my first attempt to *verify* the fix silently read
   the already-populated database and proved nothing.
4. **The backfill loop unpacked each window's end bound and never used it.** Every child would have
   re-read the same range, making the fan-out pointless. Found by a linter, not by me.
5. **The webhook endpoint had no tenant scope.** An unauthenticated request has no principal to
   derive one from, so the connection lookup ran unscoped and RLS correctly returned nothing. The
   policy caught a design error before it could become a cross-tenant read.
6. **My first tenant-hard-coding check fired on correct code** — it matched the string
   `organization_id =`, which flagged a CTE joining on the tenant column. A test that fires on
   correct code teaches everyone to ignore it.
7. **Cube's RocksDB state had been committed** by an over-broad `git add` the first time Compose
   started: 344 KB of a container's working data in the repository.

## the_guard_that_saw_nothing

Worth its own section, because it is the failure mode most likely to recur.

`test_every_org_scoped_route_is_covered_by_a_cross_tenant_test` was written in Phase B to make
CLAUDE.md's "every new endpoint gets a cross-tenant negative test in the same commit" enforceable
rather than aspirational. It walked `app.routes` looking for routes depending on `scoped_session`.

FastAPI keeps each included router as one opaque `_IncludedRouter` entry whose real routes hang off
`original_router`, so `app.routes` contained the two health endpoints and three opaque objects. The
guard found zero org-scoped routes and reported full coverage of an empty set. It had never checked
anything, and it looked identical to one that worked.

It now flattens the tree properly, is cross-checked against the OpenAPI path list so it fails if it
stops seeing routes, refuses stale entries naming routes that no longer exist, and demands a
recorded reason for each route that runs without a tenant scope. Its correction was verified by
removing an entry and watching it fail.

The general lesson: a coverage check that finds nothing passes everything. Every guard added from
here gets a test that it fails when it should.

## open_risks

| # | Risk | Status |
| --- | --- | --- |
| 1 | Compose is unverified | **Closed** in Phase C's session. 7/7 healthy in 18s. |
| 2 | Compose footprint unmeasured | **Closed.** 589 MiB idle across seven containers. |
| 3 | Seven containers plus ≈1.42M records versus p95 targets on a laptop | **Open, reduced.** Idle cost is modest; the dataset still does not exist. Re-measure in Phase F with data present. |
| 4 | 16 high-severity advisories in the legacy Cloudflare toolchain | **Contained.** Outside the workspace with its own lockfile. |
| 5 | Cube × ClickHouse × dbt-clickhouse compatibility | **Partially closed.** dbt-clickhouse builds against ClickHouse 24.8 and Cube reaches it. Cube's own models arrive in Phase D. |
| 6 | Better Auth is young for a security-critical position | **Reduced.** It holds no authorisation state; a compromise forges identity, not authority. |
| 7 | CI has never executed | **Closed** in Phase A. |
| 8 | The `identity` CI job has never run | **Closed.** Passed on `0c3eb9d`. |
| C1 | **Upload hardening the threat model already claims is absent** — decompression ratio cap, XXE, malware scanning, attachment-only serving | **Open, blocking.** Not exploitable today because no XLSX parser or download endpoint exists. Must land *before* either does. |
| C2 | The no-pickle / safe-YAML lint rule the threat model promises does not exist | **Open.** The property holds today only because nobody has written the bad line — exactly what "no guard without a test that it fails" is about. |
| C3 | `threat-model.md` T7 says "https only"; the code allows http for allowlisted private hosts | **Open, documentation.** Correct the document, not the code. |
| C4 | Secrets live in configuration, not a secret manager with rotation | **Open.** Phase I. |
| C5 | Cube idles at 18.9% CPU, more than ClickHouse | **Open.** A dev-mode container; Phase D configures it properly. |

C1 to C4 come from [the Phase C threat-model review](threat-model-review-phase-c.md), which found
two places where the threat model claims a control that is not implemented. They are recorded rather
than quietly deferred.

## footprint

Measured at idle with `pnpm dev:infra:footprint`, on a 16 GB host, immediately after a clean start
with empty volumes. **This is the floor, not the ceiling** — there is no data yet, and the ≈1.42M
record demo dataset arrives in Phase F. Re-measure then.

| Container | Memory | CPU |
| --- | --- | --- |
| clickhouse | 269.4 MiB | 4.43% |
| cube | 113.0 MiB | 18.90% |
| minio | 73.4 MiB | 0.04% |
| postgres_temporal | 58.4 MiB | 0.32% |
| temporal | 52.5 MiB | 1.99% |
| postgres | 18.8 MiB | 0.02% |
| temporal_ui | 3.8 MiB | 0.00% |
| **total** | **589 MiB** | |

Disk: 3.38 GB of images, 138 MB of volumes. Cold start including image pulls took roughly nine
minutes; warm start is 18 seconds.

Cube at 18.9% CPU while idle is the one number worth watching. It is a development-mode container
doing nothing, and it costs more CPU than ClickHouse.

## what_starting_compose_found

Three bugs, all in code that had been reviewed and none of which could be found by reading it.
This is the whole argument for the rule that a phase is not complete until its commands have run.

1. **The Temporal healthcheck probed the wrong address.** It used `127.0.0.1:7233`, but the
   frontend binds the container's network address rather than loopback, so the probe was refused
   while the server was serving perfectly. Temporal never reported healthy, which blocked
   `temporal_ui` on a dependency that was fine, which failed the whole `--wait`. Now `temporal:7233`.
2. **The Cube healthcheck used a binary the image does not have.** `wget` is not in the Cube image
   and neither is `curl`, so the probe exited 127 and the container was permanently unhealthy for
   want of a tool rather than for any reason to do with Cube. It does have node; the probe now uses
   `fetch`.
3. **`pnpm dev:infra footprint` silently ran `up`.** The package script hardcoded the `up`
   subcommand, so the argument was appended after it and ignored. The footprint command named in
   Phase A's acceptance criteria had therefore never run — and would have appeared to work, because
   `up` on a running stack succeeds. Split into `dev:infra:status` and `dev:infra:footprint`.

A fourth, environmental rather than a defect: ClickHouse asks for 262144 file descriptors, and a
container cannot raise its own hard limit, so on a constrained host the daemon refuses to start it
with `error setting rlimit type 7` — which reads like a Compose fault and is not one.
`dev-infra.sh` now clamps to the host's hard limit and prints what it did, so the gap from the
intended value is visible rather than silent.

## next_phase

**Phase D — semantic and gap engine.** *The vertical slice completes here.* Acceptance criteria in
[implementation-plan.md](implementation-plan.md#phase-d--semantic-and-gap-engine).

The data plane is in place and proven, so Phase D can start on metric definitions rather than on
plumbing. `gov_stock_truth` already computes the Stock Truth Gap's input correctly, which is the
detector's first dependency.

## next_session_prompt

```text
Read @docs/master-build-brief.md, @docs/build-state.md, @docs/implementation-plan.md,
@CLAUDE.md, @docs/data-contracts.md, @docs/gap-model.md and @docs/adr/0004-semantic-layer.md.
Start in Plan Mode.

Bring the stack up first: `pnpm dev:infra` (start dockerd if it is not running — it is installed),
then `pnpm canonical:apply` and `pnpm dbt:build`. Confirm CI is green on the branch.

Then implement Phase D: governed metric definitions as code; Cube models and tenant policies; the
detector framework with versioned config, typed I/O, replay and fixtures; the twelve detector
classes starting with source mismatch and ratio threshold; exposure and confidence models; gap
lifecycle with permissioned transitions; evidence lineage; dedupe and correlation; actions and
outcomes.

The acceptance criteria are the gate, and the first one is the hardest: a certified metric must
return the same value through Cube, the API and a dbt test — one definition, three consumers. Build
the definition as the single source and generate the others from it, because three hand-written
copies agree right up until they do not.

Hold the rules in CLAUDE.md that Phase D is most likely to break: no gap without a metric version,
a detector version, evidence and an as-of time; no modelled money without low, base, high,
assumptions and confidence; no analytical value or formula in a React component; and no causal
language on anything that is not a controlled_test outcome.

Every guard gets a test that it fails. Phase B shipped a coverage guard that checked nothing for a
whole phase, and Phase C shipped a tenant check that fired on correct code — both are recorded in
build-state as the reason for the rule.

Two items in the Phase C threat-model review are blocking prerequisites rather than backlog: C1
(upload hardening) blocks any XLSX parsing or upload-download endpoint, and C2 (the deserialisation
lint rule) should land next. Do not add either capability without its control.

Run pnpm verify, update docs/build-state.md, commit the coherent outcome and print the exact prompt
for the next fresh session.
```

## CI run 1

The workflow's first execution, on `18fe9b6`. It did what a CI skeleton is for: it found something.

| Job | Result |
| --- | --- |
| JS — format, lint, typecheck, unit | pass |
| Python — lint, typecheck, unit | pass |
| Production build | pass |
| Legacy prototype | pass — including the `npm test` fixed in Phase A |
| Dependency audit and secret scan | **fail**, then fixed |
| Visual regression | skipped, as designed |

**The audit gate failed on three real high-severity advisories**, all reachable through
`next@16.2.6` — the version inherited from the prototype:

| Package | Advisory | Fix |
| --- | --- | --- |
| `next` | GHSA-p9j2-gv94-2wf4, patched ≥ 16.2.11 | upgraded to 16.2.12 |
| `postcss` | GHSA-6g55-p6wh-862q, GHSA-r28c-9q8g-f849 | `pnpm.overrides` ≥ 8.5.26 |
| `sharp` | GHSA-f88m-g3jw-g9cj (libvips), patched ≥ 0.35.0 | `pnpm.overrides` ≥ 0.35.3 |

Plus two `turbo` advisories (low + moderate), fixed by upgrading to 2.9.14.

Fixed by upgrading and pinning, **not** by lowering `--audit-level` or adding an exception. The
threshold stays at `high`; a comment in the workflow records why.

Two secondary findings: the secret scan never ran, because steps are sequential and the audit
failure aborted the job before gitleaks; and `actions/checkout@v4` and `setup-node@v4` emitted Node
20 deprecation warnings, both bumped to v5.

## CI run 2

On `8bede8d`. The audit gate passed and **gitleaks executed for the first time and found nothing** —
the repository has now genuinely been secret-scanned, which was not true after run 1.

One job failed, caused by the action bump in the same commit rather than by any code:
`actions/setup-node@v5` enables package-manager caching by default and auto-detects the manager from
the repository root, which is pnpm. The `legacy` job is the only one using npm and never installs
pnpm, so setup-node failed before any step ran. Fixed with `package-manager-cache: false`.

Worth noting because it will recur: a job whose package manager differs from the repository default
needs that input set explicitly under setup-node v5.

## CI run 3

On `0c3eb9d`, after the production build failure on `2c84455` was fixed. **All six jobs passed**,
visual regression skipped as designed.

| Job | Result |
| --- | --- |
| JS — format, lint, typecheck, unit | pass |
| Python — lint, typecheck, unit | pass |
| **JWKS contract (Node issues, Python verifies)** | **pass**, 51s — its first execution |
| Production build | pass |
| Dependency audit and secret scan | pass, gitleaks clean |
| Legacy prototype | pass |
| Visual regression | skipped, as designed |

The failure it followed is worth recording, because the fix was not to relax the check. Next
collects page data at build time by importing every route module, so constructing Better Auth at
import made `pnpm build` demand `BETTER_AUTH_SECRET` and a database URL. `required()` still throws
and still has no default; what moved is *when* it runs. A build machine has no business holding the
signing secret, and a pipeline that needs one in order to compile is a pipeline someone has to be
given one for.

## session history

| Session | Phase | Outcome |
| --- | --- | --- |
| 1 | Audit and specification | 37 files: audit, 11 specification documents, 8 ADRs, contradiction review (14 items), Claude Code configuration. Verified regression found in `npm test`. |
| 1b | Palette | Near-black + orange, dark default, 31 contrast pairs measured rather than asserted. Both open questions closed by the repository owner. |
| 2 | A — repository and platform | Monorepo, legacy preserved with history, health probes, tokens as code, Compose, CI skeleton. `pnpm verify` exit 0. Three items unverified for lack of a daemon. |
| 3 | B — auth and tenancy | RLS proven against real PostgreSQL, ADR 0009, the Gap aggregate, invitations, Better Auth with the JWKS contract tested across runtimes. 132 tests. Seven real bugs found by execution — four in the auth and schema work, three more the moment Compose was started for the first time. |
| 4 | C — data plane | Connector SDK with the 14-point contract as library code, two Tier 1 connectors, versioned mappings, the run executor, Temporal workflows, the canonical ClickHouse layer, the governed dbt layer and the ingestion boundary. 422 tests plus 19 dbt. Seven more bugs found by execution, and a threat-model review that found two controls the document claimed but the code lacked. |

## Open product questions from the fulfilment port (Phase D)

Both were found by a differential check of the ported routing engine against
`legacy/fitos-prototype` over 3,888 input combinations, and both are *shipped*
prototype behaviour. They are preserved rather than changed, because
docs/product-spec.md §7 says the prototype's semantics carry forward and
changing them is a product decision.

1. **At Amber, a batched pick outranks staff delivery for a customer with an
   accessibility need.** `batch_pick` scores 88 against staff delivery's 63.
   §7.4's override applies only at Red, where the route is actually withheld, so
   it does not intervene here. A batched pick adds the batch window (8 minutes
   by default) to the wait.

2. **At Red with a companion present, companion collection outranks the restored
   staff delivery.** 91 against 82. The prototype's golden test does not cover
   this — its fixture has no companion — so the guarantee it appears to assert
   is fixture-dependent. A companion collecting may well be the better outcome;
   the point is that nothing currently states which is intended.

Both are covered by named tests that assert the current behaviour, so changing
either is a deliberate edit to a test that says what it is protecting.

## Deferred to Phase E

**Fulfilment copy still lives in the core.** The customer-facing explanations in
`services/api/src/fitos_api/fulfilment/policy.py` are product copy and belong in
`packs/retail` with the rest of it. They are pack-neutral today and
`packs/retail/tests/test_pack_contract.py` keeps them that way, so nothing is
broken — but the move should happen when the UI copy lands.
