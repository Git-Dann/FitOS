"""The ingestion boundary: file uploads and signed webhooks.

This is the only place untrusted bytes enter the platform, which makes it the
place worth being most careful. Everything here exists because of a specific
way that goes wrong.

**Uploads.** A file arrives from a browser, so its name, its declared content
type and its contents are all attacker-controlled:

- The **size cap is enforced while reading**, not from `Content-Length`. That
  header is supplied by the client and a chunked upload has none, so trusting it
  means a 40 GB body arrives before anyone checks.
- The **extension is derived from the declared type against an allowlist**, and
  the filename is never used to build a path. `../../etc/passwd` is a filename a
  browser will happily send.
- The **content is sniffed**, because a `.csv` that begins with `PK\\x03\\x04` is
  a zip, and a `.csv` that begins with `<?xml` is probably an XLSX somebody
  renamed. Accepting it means a parser downstream meets something it was not
  written for.
- The bytes are **written to raw storage before anything parses them**, so a
  file that fails validation can still be looked at.

**Webhooks.** A delivery is verified, deduplicated and only then parsed:

- Verification runs on the **exact bytes received**. Re-serialising the body
  first breaks the moment a source orders keys differently, and worse, can
  succeed on a payload whose meaning changed in the round trip.
- A duplicate returns **200, not 409**. A retry after a timeout is correct
  behaviour by the source; answering with an error makes it retry harder.
- Dedupe is an **atomic insert**, not check-then-insert. Two workers handling
  the same retry both see "not seen", both proceed, and the duplicate the check
  existed to prevent happens anyway.

The webhook endpoint is unauthenticated by design — a source cannot hold a
bearer token — so the signature *is* the authentication.

Its URL carries the organization as well as the connection, for the same reason
an invitation code does: the tenant scope has to be opened *before* anything can
be read, because `connections` is behind RLS and an unauthenticated request has
no principal to derive a scope from. The organization in the path is routing,
not authority — naming a tenant gets you nothing without a valid signature over
the exact bytes, and the signature is checked against the secret held for that
connection. The first version of this endpoint omitted it and looked up the
connection with no scope at all; RLS returned nothing, which is the policy
working, and the tests failed rather than the endpoint quietly reaching across
tenants.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from fitos_api.audit import record
from fitos_api.auth.deps import require, scoped_session, unscoped_session
from fitos_api.auth.principal import Principal
from fitos_api.capabilities import Capability
from fitos_api.db import organization_scope
from fitos_api.models import Connection, WebhookDelivery

router = APIRouter(prefix="/v1/ingest", tags=["ingest"])

# 200 MB. Large enough for a year of transactions as CSV, small enough that a
# handful of concurrent uploads cannot exhaust the worker.
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024

# Declared type to extension. The allowlist is the control; the filename is
# never consulted, because a filename is whatever the client felt like sending.
ALLOWED_CONTENT_TYPES: dict[str, str] = {
    "text/csv": "csv",
    "application/csv": "csv",
    "text/plain": "csv",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
}

# Leading bytes that must not appear in something declared as CSV. Each one is a
# real format that a parser downstream would meet unprepared.
FORBIDDEN_CSV_PREFIXES: tuple[tuple[bytes, str], ...] = (
    (b"PK\x03\x04", "a zip archive"),
    (b"\xd0\xcf\x11\xe0", "a legacy Office document"),
    (b"%PDF", "a PDF"),
    (b"\x7fELF", "an executable"),
    (b"<?xml", "an XML document"),
    (b"<!DOCTYPE", "an HTML document"),
)


class UploadAccepted(BaseModel):
    raw_ref: str
    digest: str
    size_bytes: int
    content_type: str
    connection_id: uuid.UUID


class WebhookAccepted(BaseModel):
    accepted: bool
    duplicate: bool
    delivery_id: str


def _raw_store(request: Request) -> Any:
    store = getattr(request.app.state, "raw_store", None)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="raw storage is not configured",
        )
    return store


async def _read_capped(upload: UploadFile) -> bytes:
    """Read the body, stopping at the cap.

    Checked while reading rather than from Content-Length, which is supplied by
    the client and absent entirely on a chunked upload.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"the upload exceeds {MAX_UPLOAD_BYTES} bytes",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _validate_upload(payload: bytes, content_type: str) -> str:
    """Return the extension to store under, or refuse.

    The declared type decides the extension; the contents decide whether the
    declaration was honest.
    """
    normalised = (content_type or "").split(";")[0].strip().lower()
    extension = ALLOWED_CONTENT_TYPES.get(normalised)
    if extension is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"content type {normalised or 'unknown'!r} is not accepted",
        )

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="the upload is empty"
        )

    if extension == "csv":
        for prefix, description in FORBIDDEN_CSV_PREFIXES:
            if payload.startswith(prefix):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"the file is declared as CSV but begins like {description}",
                )

    if extension == "xlsx" and not payload.startswith(b"PK\x03\x04"):
        # An XLSX is a zip. Something declared as one that is not will fail in
        # the parser instead, with a far less useful message.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="the file is declared as XLSX but is not a zip archive",
        )

    return extension


@router.post("/uploads", response_model=UploadAccepted, status_code=status.HTTP_201_CREATED)
async def upload_file(
    request: Request,
    principal: Annotated[Principal, Depends(require(Capability.SOURCE_MANAGE))],
    session: Annotated[Session, Depends(scoped_session)],
    connection_id: Annotated[uuid.UUID, Form()],
    resource: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> UploadAccepted:
    """Accept a file, validate it, and write it to raw storage before parsing.

    Returns the raw reference rather than parsing inline. Parsing a 200 MB file
    inside a request is how an upload endpoint becomes a denial of service on
    itself; the run that reads it is scheduled separately.
    """
    connection = session.get(Connection, connection_id)
    if connection is None:
        # 404, not 403 — a 403 would confirm the id exists in another tenant.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="connection not found")

    payload = await _read_capped(file)
    extension = _validate_upload(payload, file.content_type or "")

    store = _raw_store(request)
    reference = store.put(
        # From the verified principal, never from the form. A tenant that could
        # name its own organization here would be a cross-tenant write.
        organization_id=principal.organization_id,
        connector_key=connection.connector_key,
        resource=resource,
        payload=payload,
        content_type=file.content_type or "application/octet-stream",
        extension=extension,
    )

    record(
        session,
        principal=principal,
        action="upload.accepted",
        object_type="raw_object",
        object_id=reference.key,
        after={
            "connection_id": str(connection_id),
            "resource": resource,
            "size_bytes": reference.size_bytes,
            "digest": reference.digest,
            # The filename is recorded but never used to build a path.
            "declared_filename": file.filename,
        },
    )

    return UploadAccepted(
        raw_ref=reference.key,
        digest=reference.digest,
        size_bytes=reference.size_bytes,
        content_type=file.content_type or "application/octet-stream",
        connection_id=connection_id,
    )


@router.post("/webhooks/{organization_id}/{connection_id}", response_model=WebhookAccepted)
async def receive_webhook(
    organization_id: uuid.UUID,
    connection_id: uuid.UUID,
    request: Request,
    session: Annotated[Session, Depends(unscoped_session)],
) -> WebhookAccepted:
    """Accept a signed delivery. Unauthenticated by design; the signature authenticates.

    A source cannot hold a bearer token, so there is no principal here. What
    takes its place:

    - the organization in the path opens the tenant scope, and the connection is
      then found *inside* it — so a mismatched pair finds nothing, and the
      payload never gets a say in which tenant it lands in;
    - the signature is checked against the exact bytes received;
    - the delivery is recorded atomically, so a retry cannot become a second
      fact.

    Every failure returns the same 404. Distinguishing "no such connection" from
    "bad signature" would let anyone enumerate connection ids.
    """
    raw = await request.body()

    refusal = HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="unknown or unverified delivery"
    )

    verifier = getattr(request.app.state, "webhook_verifier", None)
    if verifier is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="webhook verification is not configured",
        )

    store = _raw_store(request)

    # Scope first, then look up. The query carries no organization predicate —
    # RLS supplies it — so a connection id from one tenant paired with another
    # tenant's organization id simply finds nothing.
    with organization_scope(session, organization_id):
        connection = session.execute(
            select(Connection).where(Connection.id == connection_id)
        ).scalar_one_or_none()
        if connection is None:
            raise refusal

        verification = verifier(connection, raw, dict(request.headers))
        if not verification.ok or not verification.delivery_id:
            raise refusal

        reference = store.put(
            organization_id=connection.organization_id,
            connector_key=connection.connector_key,
            resource="webhook",
            payload=raw,
            content_type=request.headers.get("content-type", "application/json"),
        )

        # Atomic. Check-then-insert is a race two workers lose together: both
        # see "not seen", both insert, and the duplicate this exists to prevent
        # happens anyway.
        result = session.execute(
            pg_insert(WebhookDelivery)
            .values(
                id=uuid.uuid4(),
                organization_id=connection.organization_id,
                connector_key=connection.connector_key,
                delivery_id=verification.delivery_id,
                raw_ref=reference.key,
                received_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(constraint="uq_webhook_delivery_once")
            .returning(WebhookDelivery.id)
        ).scalar_one_or_none()

    duplicate = result is None

    return WebhookAccepted(
        accepted=True,
        # 200 either way. A retry after a timeout is correct behaviour by the
        # source; answering with an error makes it retry harder.
        duplicate=duplicate,
        delivery_id=verification.delivery_id,
    )
