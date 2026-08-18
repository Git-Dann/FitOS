# ADR 0006 — Raw storage

Status: accepted · Date: 2026-08-14 · Phase: C

## Context

Evidence references must stay resolvable indefinitely, including after a mapping is corrected and
re-run. That requires an immutable copy of what the source actually sent, separate from anything the
platform derived from it. It also requires that a corrected mapping produces a *new* canonical
version rather than overwriting the old one, so a gap detected last month can still be explained.

## Decision

S3-compatible object storage for immutable raw payloads, uploads, connector response snapshots,
rejected records and Parquet exports. MinIO locally; S3 or Cloudflare R2 hosted, behind a storage
adapter so no application code names a provider.

- Object keys are content-addressed:
  `raw/{org}/{source}/{connection}/{yyyy}/{mm}/{dd}/{run_id}/{sha256}.json.zst`.
- Bucket versioning enabled; object-lock in hosted environments where available.
- The application role has **no delete permission**. Retention deletion runs under a separate
  credential and is itself audited.
- The raw object is written **before** parsing. A payload that fails to parse still leaves an
  auditable artefact, which is what makes a parse failure debuggable rather than mysterious.
- `lineage_ref` on every canonical row points at the raw object key plus the mapping version that
  produced it.

## Alternatives considered

**Raw payloads in PostgreSQL as JSONB.** Simpler locally, transactional with the run record.
Rejected: payload volume would dominate the control-plane database, backups would balloon, and
immutability would be a policy rather than a property.

**Raw payloads in ClickHouse.** Keeps ingestion in one store. Rejected: ClickHouse is a poor fit for
large opaque blobs, and mixing immutable raw with mutable canonical in one engine weakens exactly the
boundary this ADR is protecting.

**No raw layer — parse straight to canonical.** Cheapest. Rejected outright: it makes corrections
destructive and evidence unreproducible, which contradicts the product's core claim.

## Consequences

- Local Compose gains MinIO. Storage growth during repeated demo seeding is real and needs a
  documented local cleanup path in `docs/local-development.md`.
- Compression (zstd) and content addressing mean identical repeated payloads deduplicate naturally,
  which matters for polling connectors that return the same page repeatedly.
- The storage adapter must be exercised against both MinIO and a real S3-compatible endpoint in CI,
  or provider differences (multipart, conditional writes, listing semantics) surface in production.
- Data-subject deletion requires purging raw objects containing identifiers, which is a targeted
  operation against an otherwise no-delete bucket. It runs under the separate retention credential
  and is audited.
