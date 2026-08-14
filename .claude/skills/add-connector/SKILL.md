---
name: add-connector
description: Add a new data source connector to the FitOS connector SDK. Use when asked to integrate a new source, add a connector, or wire up an API, CSV template or webhook as a data source.
---

# Add a connector

Reference: `docs/connector-sdk.md`. Do not skip the manifest or the contract suite — both are CI
gates.

## Steps

1. **Decide the tier.** Tier 1 is fully testable locally with no external credentials. Tier 2 is
   production-ready code exercised against recorded fixtures, with a credential-driven live mode.

2. **Scaffold** from `connectors/sdk/template` into `connectors/<key>/`.

3. **Write the manifest** (`manifest.yaml`). Every field in the SDK doc is required. It validates
   against the JSON Schema in CI, so a missing `rate_limit_model` or `canonical_targets` fails the
   build rather than failing at runtime.

4. **Implement the protocol.** All twelve methods. For anything unsupported, raise the SDK's
   `NotSupported` — never a silent no-op that reads as success.
   - Use `ctx.http` for every request. Never construct an HTTP client: `ctx.http` is what carries
     the egress policy, rate limiter, timeouts and trace context.
   - Resolve secrets through `ctx.secrets`. Never read them from the config dict.
   - Yield batches from `extract` and checkpoint between them so a worker restart resumes.

5. **Record fixtures** with the recording harness, which redacts secrets on write. Review the
   recorded files before committing — the redactor is a safety net, not a guarantee, and a leaked
   token in a fixture is a committed secret.

6. **Write the staging mapping** and declare `canonical_targets`. Map to existing canonical facts;
   a new fact needs the data-architect agent and a data-contracts update first.

7. **Run the contract suite**: `pnpm test:integration --filter connectors/<key>`. All fourteen tests.
   The three release gates are idempotency (same extract twice → same row count), duplicate webhook
   (same signed delivery twice → one canonical fact) and egress refusal (private and redirect-to-
   private targets blocked).

8. **Add the connection card copy** for every status: configured, testing, syncing, healthy, delayed,
   schema_changed, failed, disabled, fixture. `fixture` is visibly labelled and never green.

9. **Document** rate limits, expected cadence, pagination and known quirks in
   `connectors/<key>/README.md`. Expected cadence is what `delayed` and the `data_freshness` metric
   are measured against, so a wrong value silently corrupts freshness for that source.

## Do not

- Scrape when an official API exists.
- Invent a `healthy` state without a successful credential test and a completed run in cadence.
- Drop a malformed record. Quarantine it with its reason and mapping version.
- Import a `dlt` type outside the SDK.
