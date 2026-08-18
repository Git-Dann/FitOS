# Threat model

Written before connectors or data APIs are exposed, as the brief requires. Method: STRIDE per trust
boundary, with each threat carrying a control and the test that proves the control works. A threat
without a test is not mitigated, only intended.

Target: OWASP ASVS Level 2 for the application, OWASP AISVS checks for the AI-enabled surface.

## Trust boundaries

```text
B1  browser ──▶ apps/web            untrusted client, authenticated session
B2  apps/web ──▶ services/api       server-to-server, user token forwarded
B3  services/api ──▶ PostgreSQL     RLS boundary
B4  services/api ──▶ Cube ──▶ ClickHouse   governed query boundary
B5  services/worker ──▶ external APIs      egress boundary
B6  external ──▶ webhook endpoint   unauthenticated inbound
B7  admin upload ──▶ raw storage    untrusted file content
B8  source text ──▶ AI layer        untrusted content into a model
B9  operator ──▶ demo reset/purge   destructive control boundary
```

## Threats

### T1 Tenant boundary failure — B2, B3, B4

*Elevation / information disclosure.* A request for organization A returns organization B's data
through a missed filter, a cached response, or a query built before the org context is set.

Controls: `organization_id` derived from the verified token, never from a request body or query
parameter. PostgreSQL RLS on every org-scoped table, with the application role unable to bypass it.
Cube tenant policies applied independently of the API's filter. Cache keys include the org id.

Tests: for each endpoint, a negative test that org A's token cannot read, update or delete org B's
record — expecting 404, not 403, so existence is not disclosed. A test that RLS alone blocks the
query when the service filter is deliberately removed. A test that a Cube query without an org
context is rejected rather than defaulted. Release gate.

### T2 IDOR — B2

*Elevation.* Sequential or guessable identifiers let a caller enumerate other records.

Controls: uuid v7 identifiers everywhere, authorisation checked on the object not the route, and
capability checks (`gap.assign`) rather than role-name comparisons. 404 for objects outside the
caller's org.

Tests: enumeration test over gaps, evidence, connections, mappings, quarantine records and audit
entries with a low-privilege token.

### T3 Connector credential theft — B3, B5

*Information disclosure.* Credentials read from the database, from logs, from an error message, from
a trace, or echoed by an API response.

Controls: secrets in a secret manager, or envelope-encrypted with a KMS-held key; the control plane
stores references, never plaintext. Secrets resolved at run time into a `ConnectorContext`, never
placed in the connection config object. A redaction processor on logs, errors, problem responses and
OTel spans. `test_credentials` returns a boolean and a reason code, never the value. No API response
includes a secret field, even redacted.

Tests: a unit test that a secret value in a log record is replaced; a contract test per connector
that a deliberately-logged secret does not reach the sink; a schema test that no OpenAPI response
model contains a secret-typed field.

### T4 Webhook forgery — B6

*Spoofing.* An attacker posts fabricated events, or replays a real one.

Controls: signature verification against the per-connection secret before parsing, using constant-
time comparison; timestamp tolerance window; replay cache keyed on the source delivery id;
`ReplacingMergeTree` on the source natural key so a duplicate that slips through cannot create a
duplicate fact; request size limit; the endpoint returns 2xx only after the raw payload is durably
stored.

Tests: tampered body rejected; valid body outside the timestamp window rejected; identical delivery
twice produces one canonical fact (release gate); unsigned request rejected.

### T5 CSV formula injection — B7, exports

*Code execution on the analyst's machine.* A field beginning `=`, `+`, `-`, `@`, tab or CR is
interpreted as a formula by a spreadsheet application when an export is opened.

Controls: on export, prefix any cell whose first character is in that set with a single quote, and
quote all fields. On import, treat the value as text and flag it `formula_like` in
`data_quality_flags` — do not silently strip, because silent modification of source data is its own
defect.

Tests: round-trip test with a `=cmd|...` payload asserting the exported cell is escaped; import test
asserting the flag is set and the raw object is unmodified.

### T6 SQL injection — B4

*Injection.* User input reaches a query as syntax.

Controls: no user-authored SQL from the browser reaches ClickHouse. Metric queries are built from
the certified definition; dimensions and filters are validated against an allowlist in the metric
contract; values are bound parameters. The analyst "query details" surface is read-only display of
the compiled query, not an execution path.

Tests: fuzz the metric query endpoint with injection payloads in dimension, filter and ordering
positions, asserting rejection with a stable error code rather than a database error.

### T7 SSRF through the generic REST connector — B5

*Server-side request forgery.* An admin configures a connector pointing at `169.254.169.254`,
`localhost`, an internal service, or a public host that redirects to one.

Controls: the SDK-provided HTTP client is the only egress path. It enforces an allowlist of schemes
(https only), blocks private, loopback, link-local, multicast and reserved ranges after DNS
resolution, re-validates on every redirect hop, caps redirects, pins the resolved address for the
connection to defeat DNS rebinding, and applies a response size and time limit. Optional per-org
domain allowlist for regulated tenants.

Tests: each blocked range refused; a redirect from a public host to a private one refused at the hop;
a DNS name resolving to a private address refused; redirect limit enforced. Release gate.

### T8 Prompt injection in imported text — B8

*Instruction injection.* Customer feedback, a product description, a support message or a review
contains text directing the model to exfiltrate data or take actions.

Controls: the AI layer receives a structured evidence bundle, not raw rows. Source text is wrapped in
an explicit untrusted-content envelope with instructions that content inside it is data. The model
has no database access, no write tools by default, and no ability to produce a metric value. Write
tools are separate, permissioned and require confirmation. Outputs are validated: any citation must
resolve to an id inside the bundle, and an answer citing an unknown id is rejected rather than shown.
Tenant context is applied to tool calls server-side, not passed by the model.

Tests: evaluation fixtures containing injection payloads in feedback text, asserting no tool call
outside the bundle, no fabricated citation, and no leak of another tenant's identifier. Part of the
AI evaluation suite in Phase H.

### T9 Malicious file upload — B7

*Code execution / denial of service.* A crafted XLSX, a zip bomb, a file with a spoofed extension, an
XXE payload in a spreadsheet's XML.

Controls: extension and content-type checked against sniffed content; size cap; decompression ratio
cap; XML parsing with external entity resolution disabled; parsing in the worker, never in the API
process; malware-scanning adapter interface invoked before parsing; the raw object stored and the
parse attempted afterwards, so a failed parse still leaves an auditable artefact; uploads served
back only with `Content-Disposition: attachment` and a restrictive CSP.

Tests: zip bomb rejected by ratio cap; XXE payload does not resolve an external entity; spoofed
extension rejected; oversized file rejected before buffering.

### T10 Unsafe deserialisation — B5, B6, B7

*Code execution.* Pickle, YAML `!!python/object`, or an eval-based parser on external data.

Controls: no pickle anywhere in the ingestion path; `yaml.safe_load` only, enforced by a lint rule;
all external payloads parsed into Pydantic models with strict types; no dynamic import driven by
source data.

Tests: lint rule proves absent usage; a fixture with a YAML object tag is rejected.

### T11 Data exfiltration through exports or AI tools — B2, B8

*Information disclosure.* A low-privilege user extracts restricted data through an export, a wide
metric query, or by asking the assistant.

Controls: sensitivity classification on fields; exports filtered by the caller's capabilities with
redaction markers rather than silent omission; export size limits and rate limits; every export
written to the audit log with the filter set and row count; the AI evidence bundle assembled under
the caller's permissions, so the model cannot see what the user cannot.

Tests: a frontline token receives no exposure fields in any payload, including exports and AI
responses; a restricted-sensitivity field is absent for an unauthorised caller and marked redacted;
export audit records exist for every export.

### T12 Destructive reset misuse — B9

*Denial of service / destruction.* A purge intended for the demo tenant runs against a real tenant,
or against all tenants.

Controls: purge requires the exact tenant slug typed as confirmation; the slug must resolve to a
tenant flagged `is_demo`; production mode blocks fixture seeding by default; no command may target
all organizations without a separate break-glass path with its own credential and audit trail; every
seed, reset and purge writes an audit record before it begins and after it ends; dry-run supported on
every command; a failed reset rolls back or restores the last valid snapshot.

Tests: purge against a non-demo tenant refused; purge with a mismatched slug refused; purge with no
slug refused; audit record present for each outcome including refusals; dry-run mutates nothing.
Release gate.

### T13 Audit tampering — B3

*Repudiation.* Records altered or deleted to hide an action.

Controls: append-only audit table; the application role has INSERT and SELECT only, no UPDATE or
DELETE; each event carries actor, org, action, object, before/after, request id, trace id and
timestamp; retention deletion of audit data runs under a separate credential and is itself audited.

Tests: an attempted UPDATE or DELETE as the application role fails at the database; every state
transition covered by an integration test asserting an audit row exists.

### T14 Dependency compromise — build

*Supply chain.* A malicious or vulnerable package enters the build.

Controls: committed lockfiles for both ecosystems; dependency audit and secret scanning in CI;
container image scanning; SBOM generated per release; CI runs with least privilege and no secrets
exposed to fork-originated pull requests.

Tests: CI fails on a high-severity advisory without a recorded, dated exception; SBOM artefact
produced for every release build. Note: the current repository already carries 21 advisories (16
high) with no gate — see [docs/repo-audit.md](repo-audit.md).

### T15 Session and CSRF — B1

*Spoofing.* Session theft or cross-site request forgery.

Controls: `HttpOnly`, `Secure`, `SameSite=Lax` cookies; short-lived access tokens with rotation;
CSRF tokens on cookie-authenticated state-changing requests; strict Content-Security-Policy with no
`unsafe-inline` (which the legacy prototype's inline `<style>` blocks would violate — another reason
they cannot survive the migration); HSTS; clickjacking protection; login, invitation and password
flows rate-limited per account and per IP.

Tests: CSRF token absent → rejected; CSP header asserted in an integration test; cookie attributes
asserted; rate limit returns 429 with `Retry-After`.

## Residual risks accepted for this branch

1. Better Auth is a comparatively young dependency in a security-critical position. Mitigated by the
   provider boundary in [ADR 0005](adr/0005-auth-provider.md), which keeps WorkOS or another provider
   swappable without touching product permissions.
2. Attribution-derived gaps can mislead even when correctly labelled. Mitigated by the hard
   confidence cap and the prohibition on causal language, but a determined reader can still
   over-interpret a range. Accepted and disclosed.
3. Local demo mode ships development-only auth seeding. Mitigated by a production guard, but a
   misconfigured deployment could enable it. A startup assertion fails the process if demo auth is
   enabled while the environment is production.

## Review cadence

This document is reviewed at the end of Phase C (first external data), Phase G (Tier 2 connectors)
and Phase I (hardening).

**Phase C review completed** —
[threat-model-review-phase-c.md](threat-model-review-phase-c.md). It found two places where this
document claims a control that is not implemented (the decompression/XXE/malware set under T9, and
the deserialisation lint rule under T10) and one where the implementation deliberately diverges and
this document should be corrected instead (T7 allows http for allowlisted private hosts). Read it
before trusting a "Controls:" line in this file. Every new trust boundary adds a threat entry with its test before the code
that creates the boundary merges.
