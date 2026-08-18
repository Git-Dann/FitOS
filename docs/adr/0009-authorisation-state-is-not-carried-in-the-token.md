# ADR 0009 — Authorisation state is read per request, not carried in the token

Status: accepted · Date: 2026-08-18 · Phase: B

Amends [ADR 0005](0005-auth-provider.md), which set the identity/authorisation split but did not
say what the JWT carries.

## Context

The first implementation put the caller's authority in the token: `org`, `mem`, `role` and an
optional `cap` array, all read straight into a `Principal`. It is the obvious design, it is what
most examples show, and it has two problems that only appear in operation.

**Revocation waits for expiry.** Removing someone's admin role, or removing them from the
organization entirely, changes a database row. It does not change a token that has already been
issued. Until that token expires, the holder keeps every capability it asserts. For a platform whose
whole subject is who may see modelled money and who may transition a gap, "the demotion applies
within fifteen minutes" is not an acceptable answer to an offboarding.

**A role claim is worth forging.** Every signature check in `tokens.py` exists because the payload is
worth attacking, and the payload was worth attacking mainly because of one string. The verification
is sound, but the value of defeating it should be as low as we can make it.

There is a third, quieter problem: the token and the `memberships` table were two representations of
the same fact, and nothing reconciled them.

## Decision

**The token proves identity and names an organization. It confers nothing.**

`VerifiedToken` has exactly two fields, `user_id` and `organization_id`. There is no role field and
no capability field for a claim to land in — a stale or forged `role` is not rejected, it is
structurally unreadable.

`org` is a **request**, not a grant. On every request the API:

1. verifies the signature, algorithm, issuer, audience and expiry;
2. opens the tenant scope on the *requested* organization;
3. looks for a membership for the caller **inside that scope**;
4. derives role and capabilities from that row.

Step 3 is where the authorisation actually happens, and it is worth being precise about why it is
safe. The query is `SELECT * FROM memberships WHERE user_id = :sub` — no organization predicate at
all. RLS supplies it. So "is this user a member of the organization they asked for" is answered by
the policy, and a handler cannot get it wrong by forgetting a filter, because there is no filter to
forget. No membership, no principal, no handler.

A membership for an organization the caller does not belong to therefore returns **403, not 404**:
the caller named the organization themselves, so refusing discloses nothing they did not already
supply. This is the one place the 404-not-403 rule does not apply, and it is deliberate.

## Consequences

- Demotion and revocation take effect on the next request. Two tests hold the same unexpired token
  across the change and assert the second call is refused.
- One database round trip is added per request. It is a primary-key-adjacent lookup on an indexed
  column inside a session that is being opened anyway; if it ever shows up in a profile, the cache
  belongs behind an explicit invalidation on membership writes, not in the token.
- The token is no longer a place where authority can go stale, so token lifetime becomes a pure
  session-length decision rather than a security trade-off.
- Better Auth needs to mint fewer custom claims: `sub` is standard and `org` is the active
  organization it already tracks.
- `capabilities_for` is unchanged; per-organization grants now come from `memberships.granted_capabilities`
  rather than a `cap` array, which is where they were always written anyway.

## Alternatives considered

**Short-lived tokens with claims.** A one-minute token bounds the staleness. Rejected: it trades the
problem for a refresh round trip on nearly every request, which is the database read this decision
makes anyway — without the property that the read is authoritative.

**A revocation list checked per request.** Keeps claims and adds a denylist. Rejected: it is the
same per-request lookup, plus a second source of truth that can disagree with the first, and it
handles revocation but not demotion.

**Claims plus a version counter on the organization.** Rejected as the worst of both: still a lookup,
and now a cache-invalidation problem attached to authorisation.
