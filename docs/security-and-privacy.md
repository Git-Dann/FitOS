# Security and privacy

Companion to [docs/threat-model.md](threat-model.md). That document reasons about attacks; this one
lists the controls the platform must implement and where each lives.

Baseline: OWASP ASVS Level 2 for the application, OWASP AISVS for the AI surface, WCAG 2.2 AA for
accessibility (see [docs/design-system.md](design-system.md)).

## 1. Identity and access

- Better Auth owns identity, sessions, organizations, invitations and JWT issuance with JWKS.
  FastAPI verifies against JWKS and owns authorisation. See [ADR 0005](adr/0005-auth-provider.md).
- Roles: `frontline`, `manager`, `analyst`, `admin`, `owner`, `presenter-demo`.
- Authorisation is capability-based. `can("gap.assign")`, never `role === "manager"`. Capabilities
  are defined once in the API and surfaced to the client through generated contracts.
- Every authorisation decision is server-side. The client hides controls it cannot use; hiding is a
  courtesy, the server check is the control.
- Sessions: `HttpOnly`, `Secure`, `SameSite=Lax`; short-lived access tokens with rotation; refresh
  revocable per session; sign-out revokes server-side.

## 2. Tenant isolation

- `organization_id` comes from the verified token. It is never accepted from a request body, query
  string, header or cookie.
- PostgreSQL RLS on every org-scoped table. The application database role cannot bypass RLS. The org
  id is set on the session inside the transaction that uses it.
- The governed query layer injects the org filter for every analytics query; Cube applies its own
  tenant policy independently, so a bug in one layer is not sufficient to cross the boundary.
- Cross-tenant negative tests are a release gate, not a nice-to-have.

## 3. Secrets

- Credentials live in a secret manager, or are envelope-encrypted with a KMS-held key. The control
  plane stores references.
- Secrets are resolved at run time into the connector context and never stored in a config object,
  a workflow input, a log, an error, a trace attribute or an API response.
- A redaction processor runs on logs, problem responses and OTel spans.
- Secret scanning runs in CI. Writes to `.env` and secret files are blocked by a Claude Code hook
  during development.

## 4. Input handling

- Every external payload is parsed into a strict Pydantic model. Unknown fields are recorded as
  schema drift, not silently dropped.
- Uploads: extension and content-type checked against sniffed content, size cap, decompression ratio
  cap, XML external entities disabled, malware-scanning adapter, parsing in the worker.
- Exports: CSV formula escaping, size limits, rate limits, and an audit record per export.
- Generic REST connections: https only, private and reserved address ranges blocked after DNS
  resolution, re-validated on every redirect, redirect cap, response size and time limits, optional
  per-org domain allowlist.

## 5. Data protection and privacy

- Direct personal data stays out of the analytics plane unless a documented use case requires it.
  Subjects are pseudonymous, keyed by an HMAC with a per-organization salt held in the secret manager.
- Every field carries a sensitivity classification: `public | internal | confidential | restricted`.
- Retention is configured per fact and per organization. Deletion jobs purge canonical rows, raw
  objects and derived aggregates, and record what they removed.
- Data-subject deletion is supported through the pseudonym mapping: deleting the mapping renders the
  analytics rows non-identifying, and the raw payloads containing identifiers are purged separately.
- Free-text customer feedback is `confidential` by default and passes the untrusted-content boundary
  before reaching the AI layer.
- Exposure fields are omitted server-side for the `frontline` role. This is product policy enforced
  as an authorisation rule.

## 6. Audit

- Append-only. The application role has INSERT and SELECT only.
- Every gap lifecycle transition, assignment, dismissal, mapping change, connector configuration
  change, credential test, role change, export, demo seed, reset and purge writes an event with
  actor, organization, action, object, before/after, request id, trace id and timestamp.
- Refusals are audited as well as successes — a blocked purge is exactly the event an operator needs
  to see.

## 7. Application hardening

- Strict Content-Security-Policy with no `unsafe-inline`. This is incompatible with the legacy
  prototype's inline `<style>` blocks, which is an additional reason they do not survive migration.
- HSTS, frame-ancestors denial, `X-Content-Type-Options`, referrer policy.
- CSRF tokens on cookie-authenticated state-changing requests.
- Rate limits per user, per organization and per IP on authentication, exports, metric queries and
  webhook endpoints.
- RFC 9457 problem responses with stable error codes and no internal detail — no stack traces, no
  SQL, no host names.
- Idempotency keys on write and ingest endpoints.

## 8. AI-specific controls

- The assistant operates on a structured evidence bundle assembled under the caller's permissions.
  It has no database access.
- It cannot produce or alter a numeric metric value. Numbers in an answer must be citations.
- Every answer cites internal metric, gap and evidence identifiers; a citation that does not resolve
  within the bundle causes the answer to be rejected.
- MCP tools are read-first. Write tools are separate, individually permissioned and require explicit
  confirmation.
- Evaluation fixtures cover: correct numeric citation, refusal to claim causation from correlation,
  confidence and assumption disclosure, tenant isolation, prompt injection inside source text, and
  unsupported-question handling.

## 9. Supply chain and CI

- Committed `pnpm-lock.yaml` and a locked `uv` file.
- CI: dependency audit, secret scan, container scan, SBOM generation. A high-severity advisory fails
  the build unless a dated, justified exception is recorded.
- CI has least privilege and no secrets available to fork-originated pull requests.

## 10. Verification schedule

| When | What |
| --- | --- |
| Every PR | Lint, type checks, unit tests, cross-tenant negative tests, dependency audit, secret scan |
| End of Phase B | Tenancy and RLS review |
| End of Phase C | Threat-model review for the ingestion boundary; SSRF, upload and webhook tests |
| End of Phase G | Connector credential handling and Tier 2 egress review |
| End of Phase H | AISVS checks and the AI evaluation suite |
| End of Phase I | Full ASVS L2 checklist, container scan, SBOM, backup and restore test |

Phase I completes only when there is no unresolved high-severity issue, and the final report lists
remaining medium and low risks honestly rather than omitting them.
