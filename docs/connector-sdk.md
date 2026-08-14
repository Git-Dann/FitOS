# Connector SDK

A capability-based contract. Product code depends on the SDK, never on `dlt` types or on a specific
vendor client.

## 1. Manifest

```yaml
key: shopify
name: Shopify
category: commerce
version: 1
auth_type: oauth2                 # api_key | oauth2 | hmac_webhook | file_upload | basic
supported_resources: [orders, refunds, products, inventory_levels]
supports_backfill: true
supports_incremental: true
supports_webhooks: true
supports_schema_inspection: true
rate_limit_model:
  kind: leaky_bucket
  capacity: 40
  restore_per_second: 2
required_secrets: [shop_domain, access_token]
optional_settings: [location_filter, include_test_orders]
canonical_targets:
  orders: [fact_transaction, fact_transaction_line]
  refunds: [fact_return, fact_return_line]
  inventory_levels: [fact_inventory_snapshot]
```

The manifest is data, validated against a JSON Schema in CI. Adding a connector without a valid
manifest fails the build.

## 2. Implementation interface

```python
class Connector(Protocol):
    manifest: ConnectorManifest

    def validate_config(self, config: dict) -> ValidationResult: ...
    async def test_credentials(self, ctx: ConnectorContext) -> CredentialTestResult: ...
    async def list_resources(self, ctx: ConnectorContext) -> list[ResourceDescriptor]: ...
    async def inspect_schema(self, ctx: ConnectorContext, resource: str) -> SourceSchema: ...
    async def plan_backfill(self, ctx: ConnectorContext, req: BackfillRequest) -> BackfillPlan: ...
    async def extract(self, ctx: ConnectorContext, req: ExtractRequest) -> AsyncIterator[RecordBatch]: ...
    def verify_webhook(self, ctx: ConnectorContext, raw: bytes, headers: Mapping[str, str]) -> WebhookVerification: ...
    def parse_webhook(self, ctx: ConnectorContext, raw: bytes) -> list[SourceRecord]: ...
    def staging_mapping(self, resource: str) -> StagingMapping: ...
    async def health(self, ctx: ConnectorContext) -> HealthReport: ...
    def export_checkpoint(self) -> Checkpoint: ...
    def restore_checkpoint(self, checkpoint: Checkpoint) -> None: ...
    def replay_fixture(self, name: str) -> AsyncIterator[RecordBatch]: ...
```

`ConnectorContext` carries the organization id, connection id, a secret resolver (never raw
secrets in the config dict), an HTTP client with the egress policy applied, a trace context, a
rate limiter and a progress reporter. A connector cannot construct its own HTTP client — that is how
the SSRF and egress controls are made unavoidable rather than advisory.

`extract` yields batches so a large backfill checkpoints incrementally and a worker restart resumes
rather than restarts. Every batch carries the raw payload reference so the raw object is written
before any parsing happens.

## 3. Run lifecycle

```text
configure → test_credentials → inspect_schema → plan → extract ─┬─▶ raw object (immutable)
                                                                └─▶ staging (typed)
                                                                     → mapping version applied
                                                                     → canonical facts
                                                                     → quarantine (failures)
```

Each run records: connector version, config version, mapping version, resources attempted, records
read, records written, records quarantined, checkpoints, retries, rate-limit waits, duration,
structured errors, trace id. Partial failure of one resource does not roll back another that
succeeded; the run is recorded as `partial` with per-resource outcomes.

## 4. Status model

The connection card shows exactly one of:

```text
configured · testing · syncing · healthy · delayed · schema_changed · failed · disabled · fixture
```

`fixture` is always visible and never dressed up as `healthy`. No connector card may pretend to be
connected — a green state requires a successful credential test and a completed run within the
expected cadence. `delayed` means the last run succeeded but is older than the source's declared
cadence; that distinction is what makes `data_freshness` trustworthy.

## 5. Tiers

**Tier 1 — complete and fully testable locally, no external credentials:**
CSV/XLSX upload · generic REST + OpenAPI · generic signed webhook collector · Stripe (fixture mode
plus credential-driven live path) · retail POS CSV template · footfall CSV and webhook template.

**Tier 2 — production-ready code with recorded fixtures and a credential-driven live mode:**
Shopify · GA4 Data API · Apple App Store Connect · Google Play reporting and sales.

Tier 2 connectors pass contract tests against recorded fixtures in CI. Live mode is exercised only
when credentials are present in the environment; its absence is reported, never silently skipped.

Official APIs only. Scraping is not a default integration method. Any later public-web collector
must respect access rules, rate limits and provenance.

## 6. Contract tests

Every connector, Tier 1 and Tier 2 alike, passes the same suite:

1. Manifest validates against the schema.
2. `validate_config` rejects each required field's absence with a field-specific error.
3. `test_credentials` fails closed on an invalid secret and never echoes the secret.
4. `inspect_schema` output matches the recorded fixture schema.
5. Backfill plan is deterministic for a fixed window.
6. Extract over a fixture produces a byte-identical raw object and a stable record count.
7. **Idempotency**: running the same extract twice produces the same canonical row count.
8. **Duplicate webhook**: delivering the same signed payload twice produces one canonical fact.
9. **Signature**: a tampered webhook body is rejected.
10. Checkpoint export → restore → resume yields the same final state as an uninterrupted run.
11. Rate-limit response triggers backoff, not failure.
12. A malformed record is quarantined with its reason, and the run still completes.
13. Secrets never appear in logs, errors, traces or the run record.
14. **Egress**: a connector configured with a private-network or link-local host is refused.

Tests 7, 8 and 14 are release gates named in the definition of done.

## 7. Adding a connector

Covered by the `add-connector` skill in `.claude/skills/`. Summary: scaffold from
`connectors/sdk/template`, write the manifest, implement the protocol, record fixtures with the
recording harness (which redacts secrets on write), add the staging mapping and canonical targets,
run the contract suite, add the connection card copy, document rate limits and cadence in the
connector README.
