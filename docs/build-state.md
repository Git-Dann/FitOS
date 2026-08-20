# Build state

Updated at the end of every session. Read this before starting a phase.

---

## current_phase

Phase D — semantic and gap engine.

## status

**The vertical slice is closed. The Stock Truth Gap exists end to end and is proven by execution,
not by reading code.** Eight of the nine Phase D acceptance criteria are met; the ninth — the
remaining detector classes — is partly done and scoped below.

766 Python tests pass (API 293, worker 252, connectors 129, data 85, packs 7), plus 23 dbt tests.
`pnpm verify` exits 0. Everything DB-backed runs against real PostgreSQL with
`FITOS_REQUIRE_DB_TESTS=1`, so a missing dependency fails rather than skips.

The headline: six days of detector runs over deteriorating stock readings produce **one** evolving
gap, which is then assigned, actioned and resolved with an outcome through the HTTP API, with the
audit rows and detector run records to show for it. That is `test_vertical_slice.py`, against a real
database.

Phases A, B and C remain complete; their records are below.

## what execution found that reading would not

Every one of these was surfaced by running something, and each is now covered by a test that fails
without the fix.

1. **Migrations left a pre-existing role's password unchanged.** `CREATE ROLE ... IF NOT EXISTS`
   reports success and leaves the old password in place. 125 API tests failed on `password
   authentication failed for user "fitos_app"` against a cluster whose roles predated the current
   configuration. A fresh CI database can never reproduce it; a long-lived one reproduces it once,
   at the worst time. The same statement now re-asserts `NOBYPASSRLS`, so a role granted
   `BYPASSRLS` out of band has it taken back at the next migration instead of permanently voiding
   every RLS policy while the tenancy tests keep passing.

2. **The accessibility override was applied at every capacity instead of only at Red.** A
   differential check against the prototype over 3,888 input combinations found 456 divergences —
   while all five ported behavioural tests still passed. This was in the one rule the spec calls
   non-negotiable.

3. **A golden test that silently rewrote its own expectations.** `FITOS_REGENERATE_GOLDEN` leaked
   across two commands in one shell; a run that looked like a passing comparison had rewritten the
   fixture with the output of deliberately broken code. It took three rounds to notice, because a
   rewriting golden test and a working one produce identical output. Regeneration is now refused
   when `CI` is set.

4. **A capability test that could not tell two capabilities apart.** The first dismissal test used a
   frontline role holding neither `gap.transition` nor `gap.dismiss`, so it passed just as happily
   with dismissal mapped to the wrong one. Replaced with the one caller that discriminates.

5. **Three pack-contract violations in this session's own code**, found by writing the contract test
   the spec asks for: a `retail.*` playbook id inside a core detector, and two strings naming the
   fitting room in the fulfilment policy.

6. **A golden fixture that fired on every reading it was given** — so it could not have detected a
   detector that started firing on everything. Caught by the test asserting each fixture contains a
   non-firing case.

7. **A writer rule with no test of its own.** `percentage_delta` returning 0.0 instead of NULL at a
   zero baseline passed the entire vertical slice, because no reading in it has a zero expected
   value. The candidate and the writer are two implementations of one rule; only one had a test.

## acceptance

| # | Criterion | Evidence |
| --- | --- | --- |
| 1 | A certified metric returns the same value through Cube, the API and a dbt test | `data/metrics/` — one definition compiles to all three. 26 metric-contract tests |
| 2 | Metric golden tests pass; the `examples` block executes | Executed against seeded ClickHouse, not asserted as documentation |
| 3 | Detector golden fixtures pass, including the five legacy behavioural cases with the accessibility override intact | `test_golden_fixtures.py` (5 classes) and `test_fulfilment.py` (39, incl. a 3,888-case differential grid against the prototype) |
| 4 | Scenario 2 produces **one** evolving gap across six days, not one per day | `test_vertical_slice.py` against real PostgreSQL, plus `test_detector_pipeline.py` in memory. Including the window in the dedupe key fails 8 of 9 slice stages |
| 5 | Every created gap satisfies the aggregate invariants; a property test asserts no gap without metric version, detector version, evidence and as-of time, and no exposure without low/base/high, assumptions and confidence | `test_gap_invariants.py` — enforced as database constraints, so no code path can bypass them |
| 6 | A gap can be assigned, actioned and resolved with an outcome through the API, with audit rows | `test_vertical_slice.py` asserts the full six-row audit trail in order |
| 7 | A detector run record captures versions, query hash, window, thresholds, candidates, suppressions, dedupe decisions, duration and errors | `detector_runs` (migration 0007). Written on every run, including ones that found nothing or failed |
| 8 | Exposure fields are absent from a `frontline` token's payload | Absent, not null and not zero. Two tests: one on the keys, one on the raw response text so a renamed or nested copy fails too |
| 9 | The twelve detector classes | **9 of 12 classes, covering every family in the product-spec table.** Scoped below |

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
@CLAUDE.md, @docs/design-system.md, @docs/design-concepts.md and @docs/gap-model.md.
Start in Plan Mode.

Bring the stack up first: `pnpm dev:infra` (start dockerd if it is not running — it is installed).
Export FITOS_TEST_DATABASE_URL as a psycopg 3 URL —
`postgresql+psycopg://fitos:fitos_local_only@127.0.0.1:5432/postgres` — plus FITOS_REQUIRE_DB_TESTS=1,
FITOS_APP_ROLE_PASSWORD and FITOS_AUTH_ROLE_PASSWORD, or 151 tests skip and read as passing.
Confirm CI is green on the branch.

Then implement Phase E: the design-system tokens and primitives; the app shell (Concept A); the gap
inbox with virtualisation, peek and bulk actions; gap detail (Concept C); metrics and sources
routes; the frontline, manager (Concept B heat grid), analyst and admin routes; every state; and
Storybook.

Phase D left the data behind all of this real: nine detector classes, the gap lifecycle with
permissioned transitions, actions and outcomes, and an API that already withholds exposure from a
frontline token server-side. Do not re-implement any of that in the client. In particular, exposure
is absent from the payload rather than masked — a UI that hides a number it received is not the
same control, and `test_gap_lifecycle.py` asserts the difference.

The rules Phase E is most likely to break, all from CLAUDE.md: no analytical value, formula or
currency literal in a React component; no placeholder buttons on a route marked complete; a
connector card shows its real state and `fixture` is never dressed as `healthy`; and no causal
language on anything that is not a controlled_test outcome.

Before marking any route complete: capture screenshots at 1440 x 900, 1024 x 768 and 390 x 844, have
the design-reviewer subagent compare them against docs/design-system.md, and fix the findings. Test
empty, loading, delayed, partial, error, unauthorised and offline-recovery states — a passing happy
path is not completion.

Every guard gets a test that it fails. Phase B shipped a coverage guard that checked nothing for a
whole phase; Phase C shipped a tenant check that fired on correct code; Phase D shipped a golden
test that rewrote its own expectations for three rounds. All three are recorded above as the reason
for the rule.

Two items in the Phase C threat-model review remain blocking prerequisites rather than backlog: C1
(upload hardening) blocks any XLSX parsing or upload-download endpoint, and C2 (the deserialisation
lint rule) should land next. Do not add either capability without its control.

Optional, and smaller than it looks: three of the brief's twelve detector classes are outstanding
(identity match, trend break, staffing ratio), but every family in the product-spec table already
has a class behind it. Adding one is a config plus a `detect` method; the golden-fixture coverage
test will fail until it has a fixture.

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

## Phase D remainder

Nine detector classes are implemented: source mismatch, ratio threshold, freshness, completeness,
schema drift, attribution comparison, baseline comparison, funnel drop and financial leakage.
Between them they cover **every family** in the [product-spec](product-spec.md) table. That is the position [docs/spec-review.md](spec-review.md) T3 records deliberately —
build the slice completely against the full interface, then add the rest — and the five chosen are
the ones the slice and the suppression machinery need.

Three of the brief's twelve remain — identity match, trend break, and the staffing ratio variant —
and none of them is a missing family. The staffing and fulfilment rows in the product-spec table are
configurations of the existing ratio-threshold and baseline classes; identity match and trend break
are refinements rather than new coverage. Every family in the table now has a class behind it. Each is a config
plus a `detect` method against an interface that already exists; the framework behaviours they share
— sufficiency refusal, ordering, error isolation, run records — are written and tested once, so a
new class inherits them rather than reimplementing them.

Two things must accompany each: a golden fixture (the coverage test fails on a class without one)
and, for any class emitting a data-quality gap type, an entry in the pipeline's suppression set.

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

## Design review of the ledger (Phase E)

The first ledger build was rejected on sight — "this isn't helpful to anyone… not friendly or
sellable". The design-reviewer subagent then failed the route with three P0s and nine P1s, and the
diagnosis was measurable rather than a matter of taste: a critical row and a medium row had the
identical background, title size, weight and height, and differed only in a 60 × 18 px chip — about
1.6% of the row's area. `docs/design-concepts.md` had predicted exactly this under Concept A's own
Risks ("uniform rows flatten severity … unless grouping and colour carry real weight"), the risk
was accepted, and then not mitigated.

### Fixed in this pass

| Finding | What changed |
| --- | --- |
| P0-1 · no entry point | `SituationStrip` above the ledger: open count with severity filter pills, the exposure envelope, and a stale-input count |
| P0-2 · severity carried 1.6% of the row | Severity rail down the row edge, a wash on critical rows, group headers promoted with a status dot and the group's own exposure envelope |
| P0-3 · modelled money unmarked | `▨` moved to a **prefix** on every surface, with a one-line key on the route: "modelled from an assumption · everything else is counted" |
| P1-4 · type scale collapsed | `--text-2xl` defined; route `<h1>` from 13px to `--text-xl`; row titles to `--text-base`; the strip's figure is the only `2xl` in the product |
| P1-7 · coloured chip labels | §2 verbatim: a 6px coloured dot with neutral text, glyph and word retained |
| P1-8 · tier-1 tokens in components | `--status-{critical,high,medium,low}` and `-border` added to the **semantic** tier; every component reference moved off the primitive ramps; all four hand-written light-theme overrides deleted |
| P1-9 · refusal read as helper text | `--status-critical` with a `⚠`, an invalid border on the textarea, `aria-invalid`, `aria-describedby` and `role="status"` |
| P1-10 · counts desynced after a dismissal | The inbox owns its own shell; nav badge, route title and list all derive from one piece of state |
| P1-11 · light theme unreachable | Theme toggle in the top bar, applied pre-paint by an inline script, persisted; every route now captured in both themes |
| P1-12 · 390px inverted the hierarchy | Title wraps to two lines and the low-value metadata is what gives way; every touch target at 48px |
| P2-13 · accent never used for an action | The advance action takes `--accent-fill`; the exposure band's base marker moved off accent to a neutral diamond |
| P2-18 · route advertised its own incompleteness | Roadmap clause removed from the keyboard hint |
| P3-21 · demo banner outweighed the data | One line with the paragraph behind a disclosure. Still not dismissible (product-spec §8) |

### Deliberate deviations, stated rather than drifted

- **The row is three lines, not the 32px `--row-height-compact` §5 names as the inbox default.**
  The third line is the first `recommended_actions` entry, which is the row's answer to "so what"
  and the reason it is actionable rather than informational. `--row-height-comfortable` and the
  persisted density preference §5 promises are still owed.
- **Exposure appears as a range with no base in the row.** This matches
  `docs/design-concepts.md` §Concept A and is required by `gap-model.md` §3; the base is in the peek
  next to its confidence breakdown.

### Still owed before the route can be called complete

- State coverage: loading skeleton, delayed, partial, no-data (as distinct from no-gaps), offline
  recovery. Only empty-filter, unauthorised (frontline) and one error state are captured.
- The confidence meter is four 5px pips; the whole visual difference between high and medium is one
  dot moving 50 luminance units (P2-14).
- Native `<select>` on the primary route; the `Select` primitive §7 lists is not built (P2-15).
- The metrics route is three tall cards with ~580px of dead gutter; it should be a table like
  `/sources`, which is the one screen the reviewer called good and told us to copy (P2-17).
- No `⤢ Open` from peek to detail, and the detail route is read-only (P2-19).
- The §10 lint rule forbidding tier-1 token references in components still does not exist. The
  violations are gone; the guard that would stop them coming back is not.

### What the redesign surfaced in the data

Giving exposure real visual weight immediately exposed a fixture defect that had been invisible as
grey 11px text: **NS-033 carried `isModelled: true` with `low === base === high`**, rendering as a
single exact `£26,550` standing on an organisation assumption — the precision `gap-model.md` §3
exists to forbid. The assumption is now a band (£32–£61 per conversion), and
`apps/web/lib/demo-gaps.test.ts` asserts the invariant over the whole fixture, along with exposure
ordering, the 5× wide-interval rule, the four things a gap may not exist without, and pack-scoped
playbook ids. Two of those seven contract tests failed on first run.

`packages/ui` gained a real guard too. The unresolved-reference test matched only `neutral.` and
`accent.` by name, so when the nested status ramps were added the resolver emitted
`--status-critical: [object Object]` and the test passed. It now asserts every emitted declaration
is a hex literal, and the mutation that reproduces the original bug fails it.

## Refactor onto Linear's design system (Phase E)

The visual language is now **Linear's iOS design system**, copied from
`design-md/productivity/linear/DESIGN.md` in
[Meliwat/awesome-ios-design-md](https://github.com/Meliwat/awesome-ios-design-md).

This reverses a documented decision. `docs/design-system.md` previously said the brief "explicitly
forbids copying its branding or colours" and that the orange accent was "deliberately not Linear's
blue-violet". That section is rewritten rather than left contradicting the code — §0 states the
reversal explicitly so nobody has to work out which of the two the build follows.

### What changed

| Area | Before | Now |
| --- | --- | --- |
| Canvas | `#0B0C0E` | `#08090A` — the source spec forbids `#121212` by name and a test asserts it appears nowhere |
| Accent | Orange `#F75F14`, label near-black | Purple `#5E6AD2`, label `#FFFFFF` (4.70:1) |
| Severity | Coloured chip, then a coloured row rail | Priority-bar glyph — only critical is coloured; high/medium/low differ by bar count |
| Status | Chip with a glyph and an uppercase word | Seven drawn SVG glyphs on the backlog→done arc |
| Row | Three lines, ~56px | 44px single line: status glyph → mono ref → title → scope → age → exposure → confidence → priority → avatar |
| Density | Fixed | Persisted 44px/52px preference; comfortable adds the recommended-action line |
| Type | 10–28px, 30 of 42 declarations at 10 or 11px | Inter 400/500/600, 11–28px, eight steps with per-step tracking |
| Sidebar | 216px rail | 280px, purple wash on the active item, no tab bar |
| Command menu | Did not exist | ⌘K: 560px sheet, fuzzy subsequence match, arrow keys, purple focus wash, Esc dismisses |
| Motion | None | 90–240ms, reduced-motion switch at the token level |
| Confidence | Four 5px pips | 32px segmented track plus the band word |

### The guard the palette swap needed

`--on-accent` was near-black because white on the old orange measured 3.90:1 and failed AA. White on
Linear's purple measures 4.70:1 and passes. Swapping an accent without revisiting the label colour is
exactly the change that silently breaks contrast, so a test now asserts white in both themes.

The inverse also holds and is the more interesting finding: **the source palette is internally
AA-safe only because Linear never sets text in its accent colour.** `#5E6AD2` is 4.24:1 on the canvas
and 3.59:1 on a raised row — under the body-text floor, over the 3:1 glyph floor, which is the only
way the spec ever uses it ("Active item: label `#F7F8F8`, 16pt icon `#5E6AD2`"). The token is
therefore named `--accent-glyph`, the contrast suite checks it as a non-text indicator, and a test
fails if any `--fg-*` token resolves to it.

Seven token guards were mutation-checked: canvas drifting back to `#121212`, a second accent hue,
`on-accent` reverting to near-black, the accent used as text, the selection wash colliding with the
hover ground, light inheriting the dark status ramp, and the severity rainbow returning. Each fails
exactly the assertion that names it.

### Bugs this pass produced and caught

- **`if (!open) return` after `open` stopped being a prop.** The identifier resolved to
  `window.open` — a function, therefore always truthy — so the guard silently did nothing and
  TypeScript had no complaint. A leftover name that still resolves is the worst kind.
- **`resolveRef` could not reach a three-segment token.** It split on one dot, so the nested status
  ramps emitted `--status-critical: [object Object]` and the test that should have caught it matched
  only `neutral.` and `accent.` by name. It now asserts every declaration is a hex literal.
- **Two light-theme pairs failed AA** on a "raised" step that was invented rather than taken from
  the spec. Linear's light mode has one surface; selection is carried by the purple wash it does
  define, and a test asserts the wash differs from both the canvas and the hover ground.
- **The capture script caught four touch targets under 44px and 275px of horizontal overflow** at
  390px during the pass, and refused to write screenshots until they were fixed.

### Deviations

Ten, tabulated in `docs/design-system.md` §10 with a reason each, and the machine-checkable ones
recorded in `$deviations` in `tokens.json`. The two that outrank the source spec are WCAG 2.2 AA —
which the source document does not commit to and which is not relaxed to match a value — and
`gap-model.md` §3, which requires exposure to travel with its confidence band on every surface and
so adds two values to the row's trailing zone that an issue row has no need of.

### Still owed

Unchanged from the previous review, minus the confidence meter and the density preference, which are
now done: loading/delayed/partial/no-data states, the Radix `Select` primitive (role switching moved
into the command menu but owner and dismissal-reason are still native selects), the metrics route as
a table, `⤢ Open` from peek to detail plus actions on the detail route, and the §10 lint rule
forbidding tier-1 token references in components — the violations are gone, the guard is not built.
