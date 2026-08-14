# ADR 0005 — Auth provider and the authorisation boundary

Status: accepted · Date: 2026-08-14 · Phase: B

## Context

The prototype has no authentication: all seven routes are public and the "role surfaces" at
`/demo/customer`, `/demo/associate` and `/demo/manager` are URLs, not permissions.

The platform needs organizations, memberships, roles, invitations, secure sessions for a TypeScript
web app, and token verification in a Python API. Enterprise SSO must be addable later without
rewriting product permissions.

The brief names Better Auth, which is a TypeScript library, while also specifying `/auth` as a
FastAPI resource group. Those two facts need reconciling before implementation — this ADR is the
reconciliation.

## Decision

**Split identity from authorisation.**

- **Better Auth owns identity**: users, sessions, organizations, memberships, invitations, and JWT
  issuance with a JWKS endpoint. It runs in the Node process alongside `apps/web`.
- **FastAPI owns authorisation**: it verifies JWTs against JWKS (cached, with rotation), derives
  `organization_id` from verified claims only, and evaluates capabilities.
- The `/auth` resource group in the API is **not** a second login implementation. It exposes session
  introspection, capability discovery for the current caller, and the organization switch — the
  things the API must own because they are authorisation, not identity.

**Authorisation is capability-based.** Roles map to capability sets; code asks `can("gap.assign")`.
A role-name comparison in application code is a lint error. This is what makes SSO substitution
cheap: a new identity provider supplies different role claims, and the capability map absorbs the
difference.

Roles: `frontline`, `manager`, `analyst`, `admin`, `owner`, `presenter-demo`.

## Alternatives considered

**Authorisation in Better Auth too.** Fewer moving parts. Rejected: the API, the worker, the MCP
server and any future service all need the same decisions, and only the API can enforce them for all
of them. Putting authorisation in the web tier makes every non-browser caller a special case.

**WorkOS from the start.** Enterprise SSO immediately. Rejected for this branch as heavier than
needed and dependent on an external account for local development, which conflicts with
one-command startup. The provider boundary keeps it addable.

**Roll our own sessions.** Rejected on principle: session and invitation flows are a well-solved
problem with a long tail of security detail.

## Consequences

- Two components in the auth path, so the JWKS contract must be tested explicitly: expiry, rotation,
  clock skew, algorithm confusion (reject `none` and unexpected algorithms), and audience checks.
- Better Auth is a comparatively young dependency in a security-critical position. Recorded as an
  accepted residual risk in [docs/threat-model.md](../threat-model.md#residual-risks-accepted-for-this-branch),
  mitigated by the provider boundary.
- Passwordless and social login are added only after the base flow is tested.
- Demo identities are seeded through a development-only path; startup fails if that path is enabled
  while the environment is production.
- The `frontline` exposure exclusion is implemented as a capability (`gap.view_exposure`), not as a
  UI condition, so it holds for the API, exports and the AI layer without three separate rules.
