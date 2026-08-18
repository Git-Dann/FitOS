"""Raw object storage. Written before parsing, never mutated after.

Two rules from the data contract, and both are structural here rather than
procedural:

**Immutable.** There is no update and no overwrite. `put` refuses a key that
already holds different bytes. A correction is a new mapping version and a
re-run over the same raw object, never an edit — because the raw layer is what
makes a canonical row reproducible, and a mutable raw layer makes every
downstream claim unfalsifiable.

**Written first.** The raw object exists before anything parses it, so a record
that fails parsing still has bytes to point at. Quarantine with a reason is
only useful if the thing that was rejected can still be looked at.

Keys are content-addressed:

    org/{organization_id}/{connector}/{resource}/{yyyy}/{mm}/{dd}/{sha256}.{ext}

The digest is the object's identity, which gives idempotency for free: the same
extract run twice writes the same key with the same bytes, so a replay cannot
produce two raw objects and cannot produce two lineage references. The date
path is for lifecycle rules and for a human reading a bucket listing; the
organization prefix is what makes a per-tenant deletion job possible without a
full scan.

The interface is deliberately narrow, and there is a local filesystem
implementation as well as S3/MinIO, so raw-layer behaviour is testable without
a bucket.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID


class RawObjectConflictError(Exception):
    """The key exists and holds different bytes.

    Only reachable through a hash collision or a caller passing a key it
    computed itself. Either way it means the immutability assumption is broken,
    which is worth an exception rather than a silent overwrite.
    """


@dataclass(frozen=True)
class RawObjectRef:
    """Where the bytes are, and what they were.

    `digest` travels with the key so a consumer can verify what it read without
    re-deriving the key format.
    """

    key: str
    digest: str
    size_bytes: int
    content_type: str

    def __str__(self) -> str:
        return self.key


def raw_key(
    *,
    organization_id: UUID,
    connector_key: str,
    resource: str,
    payload: bytes,
    at: datetime | None = None,
    extension: str = "json",
) -> tuple[str, str]:
    """The key and digest for a payload. Pure, so it is testable and stable."""
    digest = hashlib.sha256(payload).hexdigest()
    when = (at or datetime.now(UTC)).astimezone(UTC)
    key = f"org/{organization_id}/{connector_key}/{resource}/{when:%Y/%m/%d}/{digest}.{extension}"
    return key, digest


class RawStore(ABC):
    """Put and get. No update, no delete-by-key.

    Deletion exists only through the retention path, which purges by
    organization and age and writes an audit record — never as a casual
    operation a connector could reach.
    """

    @abstractmethod
    def put(
        self,
        *,
        organization_id: UUID,
        connector_key: str,
        resource: str,
        payload: bytes,
        content_type: str = "application/json",
        at: datetime | None = None,
        extension: str = "json",
    ) -> RawObjectRef: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...


class FilesystemRawStore(RawStore):
    """For tests and local development. Same semantics as the object store."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / key

    def put(
        self,
        *,
        organization_id: UUID,
        connector_key: str,
        resource: str,
        payload: bytes,
        content_type: str = "application/json",
        at: datetime | None = None,
        extension: str = "json",
    ) -> RawObjectRef:
        key, digest = raw_key(
            organization_id=organization_id,
            connector_key=connector_key,
            resource=resource,
            payload=payload,
            at=at,
            extension=extension,
        )
        path = self._path(key)
        if path.exists():
            # Same key means same digest means same bytes. Re-writing would be
            # harmless but pointless; different bytes would mean the
            # content-addressing is broken and must not pass quietly.
            if path.read_bytes() != payload:
                raise RawObjectConflictError(f"{key} exists with different content")
            return RawObjectRef(
                key=key, digest=digest, size_bytes=len(payload), content_type=content_type
            )

        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temporary name and rename, so a crash mid-write cannot
        # leave a truncated object under a key that claims a digest.
        temporary = path.with_suffix(path.suffix + ".partial")
        temporary.write_bytes(payload)
        temporary.rename(path)
        return RawObjectRef(
            key=key, digest=digest, size_bytes=len(payload), content_type=content_type
        )

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


class S3RawStore(RawStore):
    """MinIO in development, S3-compatible storage in deployment (ADR 0006).

    Object-lock and versioning belong on the bucket, configured by
    infrastructure rather than asserted by the client: a client that promises
    immutability it does not control is a client that promises nothing.
    `put` still refuses a conflicting overwrite so the guarantee holds even
    against a bucket that was misconfigured.
    """

    def __init__(self, client: object, bucket: str) -> None:
        # Typed as object so the SDK does not depend on boto3 at import time;
        # the runner injects a client.
        self._client = client
        self.bucket = bucket

    def put(
        self,
        *,
        organization_id: UUID,
        connector_key: str,
        resource: str,
        payload: bytes,
        content_type: str = "application/json",
        at: datetime | None = None,
        extension: str = "json",
    ) -> RawObjectRef:
        key, digest = raw_key(
            organization_id=organization_id,
            connector_key=connector_key,
            resource=resource,
            payload=payload,
            at=at,
            extension=extension,
        )
        if self.exists(key):
            existing = self.get(key)
            if existing != payload:
                raise RawObjectConflictError(f"{key} exists with different content")
            return RawObjectRef(
                key=key, digest=digest, size_bytes=len(payload), content_type=content_type
            )

        self._client.put_object(  # type: ignore[attr-defined]
            Bucket=self.bucket,
            Key=key,
            Body=payload,
            ContentType=content_type,
            ChecksumSHA256=_b64_digest(payload),
        )
        return RawObjectRef(
            key=key, digest=digest, size_bytes=len(payload), content_type=content_type
        )

    def get(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self.bucket, Key=key)  # type: ignore[attr-defined]
        body: bytes = response["Body"].read()
        return body

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)  # type: ignore[attr-defined]
        except Exception:
            return False
        return True


def _b64_digest(payload: bytes) -> str:
    import base64

    return base64.b64encode(hashlib.sha256(payload).digest()).decode()
