# Threat-model review — the ingestion boundary (end of Phase C)

Required by [threat-model.md](threat-model.md#review-cadence): *"reviewed at the end of Phase C
(first external data)"*. Phase C is where untrusted bytes first enter the platform, so this walks the
threats that touch that boundary — T3, T4, T7, T9, T10, T13 — and states, for each, what is actually
implemented, what test proves it, and what is **not** done.

The point of the exercise is the last column. A review that concludes everything is fine is a review
that was not performed.

## Summary

| # | Threat | Status | Evidence |
| --- | --- | --- | --- |
| T3 | Connector credential theft | **Mitigated** | Secrets never in config; resolver records keys not values; redaction tested against the realistic leak |
| T4 | Webhook forgery | **Mitigated** | Signature over exact bytes, timestamp inside the signature, atomic dedupe |
| T7 | SSRF | **Mitigated, release gate** | 38 egress tests; connector-level and redirect-level refusals |
| T9 | Malicious file upload | **Partially mitigated** | Sniffing, size cap, path safety done. **Decompression ratio cap, XXE hardening and malware scanning are not implemented** |
| T10 | Unsafe deserialisation | **Mitigated by construction, unproven by lint** | No pickle, no yaml.load anywhere in the ingestion path. **The lint rule the document promises does not exist** |
| T13 | Audit tampering | **Mitigated** | Append-only by grant absence; run counts frozen by trigger |

Two entries are honest failures against what `threat-model.md` already claims. They are recorded
here rather than quietly deferred, and both are carried into the Phase C open risks.

## T3 — Connector credential theft

**Implemented.** Secrets never enter the connector config dict; they arrive through a
`SecretResolver` that returns a value and keeps no reference. The resolver's `__repr__` renders keys
only, because a resolver that renders its contents ends up in the first traceback that touches one.
`connections.config` carries a CHECK constraint refusing anything matching
`(password|secret|token|api[_-]?key|private[_-]?key)`, so a database backup or a support export of
that table yields nothing usable.

The run record lists **which keys were used, never their values**, so an incident can establish what
a run touched without the record itself becoming the leak.

**The leak that actually happens** is not `log(api_key)` — nobody writes that. It is a library
raising an exception whose message quotes the request URL, with the key in the query string. That
exact case is tested: a transport failure quoting `https://api.example/?key=sk-live-...` comes back
as `[redacted:api_key]`. The REST connector also sends its key as an `Authorization` header rather
than a query parameter, with a test asserting the key never appears in the URL, because a URL ends
up in access logs and referrers regardless of what we do with our own errors.

**Not done.** Secrets are held in configuration, not in a secret manager with rotation and per-run
leases. That is a Phase I item and is listed as such.

## T4 — Webhook forgery

**Implemented.** The signature is computed over the **exact bytes received**, never a re-serialised
body — re-serialising fails the moment a source orders keys differently and, worse, can *succeed* on
a payload whose meaning changed in the round trip. Comparison is `hmac.compare_digest`.

The timestamp is **inside** the signed material, not merely a header, so an attacker cannot edit it;
deliveries outside a five-minute window are refused in both directions, because a far-future
timestamp would otherwise extend the replay window indefinitely.

Replay is closed by an atomic `INSERT ... ON CONFLICT DO NOTHING` against a unique constraint on
`(organization_id, connector_key, delivery_id)`. Check-then-insert is a race two workers lose
together: both see "not seen", both proceed, and the duplicate the check existed to prevent happens
anyway. Keyed per organization because sources number deliveries from 1 for everybody.

A duplicate returns **200, not 409** — a retry after a timeout is correct behaviour by the source,
and an error makes it retry harder.

**A design change made during this phase.** The endpoint is unauthenticated by necessity: a source
cannot hold a bearer token. The first implementation looked up the connection with no tenant scope,
because there is no principal to derive one from — and RLS correctly returned nothing, so the tests
failed rather than the endpoint reaching across tenants. The URL now carries the organization as
routing: the scope is opened from it, and the connection is found *inside* that scope with no
organization predicate of its own, so a mismatched pair finds nothing. Naming a tenant gets an
attacker nothing without a valid signature.

Every failure returns one indistinguishable 404. Separating "no such connection" from "bad
signature" would let anyone enumerate connection ids.

## T7 — SSRF

**Implemented, and a release gate.** The SDK-provided client is the only egress path, and the
contract suite reads each connector's source and fails if it constructs its own — the policy is only
unavoidable while there is no second client.

Scheme allowlist; DNS resolved and **every** returned address judged, so a host answering with one
public and one private address is refused; the connection is made to an address that was actually
checked, with the hostname preserved for Host and SNI, which closes the rebind; every redirect hop
re-checked; redirect count capped; response size capped while streaming rather than from
`Content-Length`, which the source supplies and a chunked response omits.

IPv4-mapped IPv6, 6to4 and Teredo forms are unwrapped before judging, because
`IPv6Address('::ffff:127.0.0.1').is_loopback` is `False` and a naive check lets the whole private v4
space through.

A refusal names the reason and the host but **never the resolved address**, because otherwise it is
a network-mapping oracle, one DNS record at a time.

**Deviation from the document.** `threat-model.md` says "https only". The implementation allows
`http` as well. This is deliberate: a self-hosted source on a private network, reached through the
per-connection allowlist, will not have a public certificate, and refusing `http` outright would push
those tenants toward disabling verification instead. The address checks are the control; the scheme
allowlist exists to exclude `file:`, `gopher:` and similar. **The document should be corrected rather
than the code** — recorded here so the next reviewer does not "fix" the code to match a sentence.

## T9 — Malicious file upload — *partially mitigated*

**Implemented.** Content type checked against an allowlist; contents sniffed against the declared
type, so a `.csv` beginning `PK\x03\x04`, `%PDF`, `\x7fELF`, `<?xml` or `<!DOCTYPE` is refused; size
capped while reading rather than from `Content-Length`; the filename never used to build a path,
with a test uploading `../../../../etc/passwd` and asserting the stored key derives from the
organization, connector, resource and content digest; the raw object written **before** any parse, so
a failed parse still leaves an auditable artefact.

**Not implemented, and the threat model already claims them:**

- **Decompression ratio cap.** No XLSX parsing exists yet, so there is currently no zip to bomb —
  but the moment XLSX parsing lands, an XLSX *is* a zip and the cap has to exist first.
- **XXE hardening.** Same dependency: no XML parser is invoked today, and the control must precede
  the parser rather than follow it.
- **Malware-scanning adapter.** Not present; no interface, no invocation point.
- **`Content-Disposition: attachment` on served uploads.** No endpoint serves an upload back yet.

None of these are exploitable today, because the code they would protect does not exist. All four
become exploitable the day XLSX parsing or upload download is added, which makes them a **blocking
prerequisite for that work** rather than a backlog item. Recorded in the Phase C open risks.

## T10 — Unsafe deserialisation

**Mitigated by construction.** No `pickle` anywhere. `yaml.safe_load` is the only YAML entry point.
Every external payload is parsed into a Pydantic model with strict types, and connector manifests use
`extra="forbid"` so an unexpected key is an error rather than a silently ignored setting.

**Not done.** The document promises "*enforced by a lint rule*" and **no such rule exists**. The
property currently holds because nobody has written the bad line, which is exactly the situation
CLAUDE.md's "no guard without a test that it fails" is about. The AST checker that enforces
capabilities-not-roles is the obvious template. Recorded as an open risk.

## T13 — Audit tampering

**Implemented.** `audit_events` grants the application role `SELECT, INSERT` and nothing else, so
append-only is a property of the grant rather than of a trigger somebody can disable. The same
applies to `mapping_versions`, `connector_runs`, `quarantined_records` and `webhook_deliveries`.

Two rules needed `OLD` and `NEW` and are therefore triggers: an applied mapping version is frozen
except for `is_active`, and a finished run's counts and outcome are final. The second exists because
the temptation is to tidy up a rejected count after the fact, which is precisely what makes the count
untrustworthy.

Migration `0001` refuses to downgrade, because rolling it back would drop the audit table.

## New boundaries introduced in Phase C

The cadence rule says *"every new trust boundary adds a threat entry with its test before the code
that creates the boundary merges"*. Phase C added three:

1. **Raw object storage** (B7 extended). Content-addressed and immutable; `put` refuses a key holding
   different bytes; no delete except through the retention path. Two tenants uploading identical
   files get different keys — same digest, different prefix — which is also what makes a per-tenant
   deletion job possible without a full scan.
2. **The mapping interpreter.** Transforms are a closed set of eight, not an expression language. An
   expression language configured by whoever can edit a connection is remote code execution, and "it
   is only a formula" is how that ships. An unknown transform is refused at save time, because a typo
   that quietly does nothing produces plausible wrong numbers.
3. **Temporal workflows.** Workflow bodies are deterministic, enforced by a static check over the
   AST that fails on wall-clock time, randomness, I/O, or a retry loop — a loop in a workflow body
   re-executes on replay and multiplies attempts, which is how a rate-limited source becomes a banned
   client. An `EgressBlockedError` is explicitly non-retryable: a blocked destination is a decision,
   not a transient failure.

## Open risks carried out of this review

| # | Risk | Blocking for |
| --- | --- | --- |
| C1 | Decompression ratio cap, XXE hardening, malware scanning and attachment-only serving are absent | XLSX parsing and any upload-download endpoint |
| C2 | The no-pickle / safe-YAML lint rule the threat model promises does not exist | Should land next phase; the property holds today only by nobody having written the bad line |
| C3 | `threat-model.md` T7 says "https only"; the code allows http for allowlisted private hosts | Correct the document, not the code |
| C4 | Secrets live in configuration, not a secret manager with rotation | Phase I |

Reviewed at the end of Phase C. Next review: Phase G (Tier 2 connectors).
