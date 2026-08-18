# Configuration

Every environment variable the platform reads, what breaks without it, and where the value comes
from. Nothing here has a default that would be safe in production; where a default exists it is
noted and it is the *restrictive* one.

**No secret is ever written to a file in this repository.** There is no `.env` in version control
and no `.env.example` with a plausible-looking value in it, because a placeholder secret that works
locally is a secret that reaches production the first time someone copies the file. Values come from
the environment, and in deployment from the platform's secret store.

## Application — `services/api`

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `FITOS_ENVIRONMENT` | no | `local` | One of `local`, `preview`, `staging`, `production`. |
| `FITOS_DATABASE_URL` | yes in deployment | — | SQLAlchemy URL. Connect as `fitos_app`, never as the owner: the application role is `NOBYPASSRLS`, and that is the whole point of having two roles. |
| `FITOS_DEMO_AUTH_ENABLED` | no | `false` | Development-only identity seeding. **The process refuses to start** if this is true while `FITOS_ENVIRONMENT=production` (`test_guards.py`). |

## Migrations — `services/api/migrations`

Migrations run as the schema owner, not the application role, because the application role cannot
alter policies.

| Variable | Required | Notes |
| --- | --- | --- |
| `FITOS_MIGRATION_DATABASE_URL` | yes | Owner connection. Falls back to `FITOS_DATABASE_URL` if unset, which is a convenience for local work and a mistake in deployment. |
| `FITOS_APP_ROLE_PASSWORD` | yes | Password for the `fitos_app` role, created by migration 0001. There is **no default**: a default here becomes a production credential. Must match `[A-Za-z0-9_.-]{8,128}` — it is interpolated into DDL, which cannot take a bound parameter, so it is validated to make sure it cannot escape the literal. |
| `FITOS_AUTH_ROLE_PASSWORD` | yes | Same, for the `fitos_auth` role created by migration 0004. |

Both role passwords are **re-asserted on every migration**, not only when the role is first
created. Creating the role only when absent is the obvious shape and it is wrong on any cluster
the migration has run against before: the role keeps whatever password it was first given, the
migration reports success, and the application then cannot authenticate. The same statement
re-asserts `NOBYPASSRLS`, so a role that was granted `BYPASSRLS` out of band has it taken back
at the next migration rather than permanently voiding every RLS policy.

## Identity — `apps/web`

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `BETTER_AUTH_SECRET` | yes | — | Signs session cookies **and encrypts the stored JWKS private keys**. Rotating it does not re-encrypt existing keys, it orphans them: every stored signing key becomes undecryptable and must be cleaned up. Treat rotation as a key-rotation event, not a config change. At least 32 random bytes. |
| `FITOS_AUTH_DATABASE_URL` | yes | — | node-postgres URL. Connect as `fitos_auth`. That role holds the identity tables — including the password hashes and the private signing keys — and `fitos_app` is granted nothing on any of them, so an injection in the API cannot reach a key it has no privilege to see. |
| `FITOS_AUTH_ISSUER` | no | `http://localhost:3000` | Becomes the `iss` claim. Must match the API's expected issuer exactly. |
| `FITOS_AUTH_AUDIENCE` | no | `fitos-api` | Becomes the `aud` claim. Must match the API's expected audience exactly. |

Issuer and audience are checked on every request, so a mismatch between the two sides is a total
outage rather than a subtle bug. `test_jwks_contract.py` mints a real token and verifies it with the
real verifier, so a mismatch fails in CI instead.

## Test-only

These exist to stop a skipped test reading as a passing one.

| Variable | Notes |
| --- | --- |
| `FITOS_TEST_DATABASE_URL` | Admin connection for the throwaway databases the suite creates. Without it every tenancy test skips. |
| `FITOS_REQUIRE_DB_TESTS` | Turns those skips into errors. Set in CI: a postgres service that fails to start would otherwise produce a green build with tenancy unverified, which is worse than a red one. |
| `FITOS_REQUIRE_JWKS_CONTRACT` | The same idea for the cross-runtime auth test, which also needs Node and an install. Set in the `identity` CI job. |

## Roles

Four database roles, and the separation between them is a security control rather than tidiness.

| Role | Holds | Notably cannot |
| --- | --- | --- |
| owner | Schema, migrations | — (exempt from RLS by design; never used to serve a request) |
| `fitos_app` | Org-scoped tables | `NOBYPASSRLS`. No `DELETE` on `audit_events`, `gaps` or `invitations`. **No access at all** to `jwks`, `accounts`, `sessions` or `verifications`. |
| `fitos_auth` | Identity tables and `users` | Nothing on `organizations`, `memberships`, `gaps` or `audit_events`. |
| `PUBLIC` | — | `EXECUTE` on `user_organizations`, which is revoked; PostgreSQL grants it by default and the revoke is asserted in `test_migrations.py`. |
