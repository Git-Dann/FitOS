"""CSV upload against the shared contract, plus what is specific to files.

The 14-point suite is inherited rather than reimplemented. What is here on top
of it is the parsing behaviour that only a file connector has, and every one of
those tests exists because the input is a spreadsheet export written by
somebody who was not thinking about us.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fitos_connector_csv.connector import CsvUploadConnector
from fitos_connector_sdk.context import ConnectorContext
from fitos_connector_sdk.contract_tests import ConnectorContractTests, ConnectorHarness
from fitos_connector_sdk.raw_store import FilesystemRawStore
from fitos_connector_sdk.types import ExtractRequest, SourceRecord

ORG = uuid4()

GOOD_CSV = b"""order_id,occurred_at,amount_minor,currency
A-1,2026-05-01T10:00:00Z,1250,GBP
A-2,2026-05-01T10:05:00Z,4300,GBP
A-3,2026-05-01T10:09:00Z,999,GBP
"""


def _context(tmp_path: Path, payload: bytes = GOOD_CSV, **overrides: object) -> ConnectorContext:
    store = FilesystemRawStore(tmp_path / "raw")
    ref = store.put(
        organization_id=ORG,
        connector_key="csv_upload",
        resource="transactions",
        payload=payload,
        content_type="text/csv",
        extension="csv",
    )
    config: dict[str, object] = {
        "resource": "transactions",
        "raw_ref": ref.key,
        "raw_store": store,
    }
    config.update(overrides)
    return ConnectorContext.create(organization_id=ORG, connection_id=uuid4(), config=config)


class TestCsvUploadContract(ConnectorContractTests):
    """The shared 14 points. Nothing connector-specific is asserted here."""

    @pytest.fixture
    def harness(self, tmp_path: Path) -> ConnectorHarness:
        ctx = _context(tmp_path)
        return ConnectorHarness(
            connector=CsvUploadConnector(),
            context=ctx,
            resource="transactions",
            organization_id=ORG,
            malformed_record=SourceRecord(
                source_record_id="bad:1",
                payload={
                    "order_id": "",
                    "occurred_at": "not-a-date",
                    "amount_minor": "-50",
                    "currency": "POUNDS",
                },
                raw_ref=str(ctx.config["raw_ref"]),
            ),
            expected_flag="missing_required",
        )


# ---------------------------------------------------------------------------
# Idempotency, in the form that actually matters
# ---------------------------------------------------------------------------


async def test_the_same_file_uploaded_twice_produces_identical_record_ids(
    tmp_path: Path,
) -> None:
    """RELEASE GATE, in its real-world shape.

    Somebody uploads the same export twice — a retry after a timeout, or two
    people doing the same job. The ids are derived from the content digest and
    the row position, so the second upload replaces the first rather than
    doubling the day's revenue.
    """
    connector = CsvUploadConnector()
    first_ctx = _context(tmp_path / "one")
    second_ctx = _context(tmp_path / "two")

    async def ids(ctx: ConnectorContext) -> list[str]:
        out: list[str] = []
        async for batch in connector.extract(ctx, ExtractRequest(resource="transactions")):
            out.extend(r.source_record_id for r in batch.records)
        return out

    assert await ids(first_ctx) == await ids(second_ctx)


def test_the_raw_key_is_the_content_digest(tmp_path: Path) -> None:
    """Same bytes, same key — which is what makes re-upload a no-op at the raw layer."""
    store = FilesystemRawStore(tmp_path)
    first = store.put(
        organization_id=ORG, connector_key="csv_upload", resource="transactions", payload=GOOD_CSV
    )
    second = store.put(
        organization_id=ORG, connector_key="csv_upload", resource="transactions", payload=GOOD_CSV
    )
    assert first.key == second.key
    assert first.digest == second.digest


def test_different_content_gets_a_different_key(tmp_path: Path) -> None:
    store = FilesystemRawStore(tmp_path)
    a = store.put(
        organization_id=ORG, connector_key="csv_upload", resource="transactions", payload=GOOD_CSV
    )
    b = store.put(
        organization_id=ORG,
        connector_key="csv_upload",
        resource="transactions",
        payload=GOOD_CSV + b"A-4,2026-05-01T11:00:00Z,100,GBP\n",
    )
    assert a.key != b.key


def test_two_organizations_never_share_a_raw_key(tmp_path: Path) -> None:
    """Identical files from two tenants must not collide.

    The digest is the same; the organization prefix is what keeps them apart,
    and what makes a per-tenant deletion job possible without a full scan.
    """
    store = FilesystemRawStore(tmp_path)
    one = store.put(
        organization_id=uuid4(),
        connector_key="csv_upload",
        resource="transactions",
        payload=GOOD_CSV,
    )
    two = store.put(
        organization_id=uuid4(),
        connector_key="csv_upload",
        resource="transactions",
        payload=GOOD_CSV,
    )
    assert one.key != two.key
    assert one.digest == two.digest


# ---------------------------------------------------------------------------
# Quarantine — every case is a real spreadsheet
# ---------------------------------------------------------------------------


def _validate(payload: dict[str, object]) -> set[str]:
    connector = CsvUploadConnector()
    record = SourceRecord(source_record_id="x", payload=payload, raw_ref="ref")
    return {reason.flag.value for reason in connector.validate_record("transactions", record)}


def test_a_missing_required_field_is_quarantined() -> None:
    assert "missing_required" in _validate(
        {
            "order_id": "",
            "occurred_at": "2026-05-01T10:00:00Z",
            "amount_minor": "1",
            "currency": "GBP",
        }
    )


def test_an_unparseable_date_is_quarantined() -> None:
    assert "type_coerced" in _validate(
        {"order_id": "A", "occurred_at": "01/05/2026", "amount_minor": "1", "currency": "GBP"}
    )


def test_a_future_dated_row_is_quarantined() -> None:
    """Usually a timezone bug or a spreadsheet auto-format.

    Left alone it silently poisons every time-window aggregate it lands in,
    and it is invisible because the row looks perfectly well-formed.
    """
    assert "future_dated" in _validate(
        {
            "order_id": "A",
            "occurred_at": "2099-01-01T00:00:00Z",
            "amount_minor": "1",
            "currency": "GBP",
        }
    )


def test_a_negative_amount_is_quarantined_rather_than_treated_as_a_refund() -> None:
    """A return is its own fact. Accepting a negative here halves someone's revenue."""
    assert "negative_amount" in _validate(
        {
            "order_id": "A",
            "occurred_at": "2026-05-01T10:00:00Z",
            "amount_minor": "-500",
            "currency": "GBP",
        }
    )


def test_a_bad_currency_code_is_quarantined() -> None:
    assert "currency_mismatch" in _validate(
        {
            "order_id": "A",
            "occurred_at": "2026-05-01T10:00:00Z",
            "amount_minor": "1",
            "currency": "POUNDS",
        }
    )


def test_one_row_can_be_wrong_in_several_ways_at_once() -> None:
    """Reporting only the first fault means the next one is found on the next run."""
    flags = _validate(
        {"order_id": "", "occurred_at": "nope", "amount_minor": "-1", "currency": "XX"}
    )
    assert len(flags) >= 3, flags


def test_a_good_row_produces_no_reasons() -> None:
    assert (
        _validate(
            {
                "order_id": "A-1",
                "occurred_at": "2026-05-01T10:00:00Z",
                "amount_minor": "1250",
                "currency": "GBP",
            }
        )
        == set()
    )


async def test_a_bad_row_does_not_stop_the_run(tmp_path: Path) -> None:
    """Contract test 12. The other rows still arrive, and the count is reported."""
    mixed = (
        b"order_id,occurred_at,amount_minor,currency\n"
        b"A-1,2026-05-01T10:00:00Z,1250,GBP\n"
        b",2026-05-01T10:01:00Z,900,GBP\n"
        b"A-3,2026-05-01T10:02:00Z,700,GBP\n"
    )
    connector = CsvUploadConnector()
    ctx = _context(tmp_path, payload=mixed)

    records = []
    async for batch in connector.extract(ctx, ExtractRequest(resource="transactions")):
        records.extend(batch.records)

    assert len(records) == 3, "the run stopped early or dropped a row"
    rejected = [r for r in records if connector.validate_record("transactions", r)]
    assert len(rejected) == 1


# ---------------------------------------------------------------------------
# Parsing files written by spreadsheets
# ---------------------------------------------------------------------------


async def test_a_utf8_bom_does_not_corrupt_the_first_column(tmp_path: Path) -> None:
    """Excel writes one by default.

    Decoded as plain utf-8 the first header becomes "﻿order_id", so every
    lookup of "order_id" misses and every row reports a missing required field
    — a whole-file failure that looks like a data problem.
    """
    connector = CsvUploadConnector()
    ctx = _context(tmp_path, payload=b"\xef\xbb\xbf" + GOOD_CSV)

    async for batch in connector.extract(ctx, ExtractRequest(resource="transactions")):
        assert "order_id" in batch.records[0].payload
        assert batch.records[0].payload["order_id"] == "A-1"
        break


async def test_a_semicolon_delimited_export_is_read_correctly(tmp_path: Path) -> None:
    """The European default. Sniffed, and overridable when sniffing is wrong."""
    connector = CsvUploadConnector()
    ctx = _context(
        tmp_path,
        payload=(
            b"order_id;occurred_at;amount_minor;currency\nA-1;2026-05-01T10:00:00Z;1250;GBP\n"
        ),
    )
    async for batch in connector.extract(ctx, ExtractRequest(resource="transactions")):
        assert batch.records[0].payload["amount_minor"] == "1250"
        break


async def test_duplicate_column_names_do_not_overwrite_each_other(tmp_path: Path) -> None:
    """A naive DictReader keeps only the last, losing a column without a word."""
    connector = CsvUploadConnector()
    ctx = _context(tmp_path, payload=b"order_id,amount_minor,amount_minor\nA-1,100,200\n")
    async for batch in connector.extract(ctx, ExtractRequest(resource="transactions")):
        payload = batch.records[0].payload
        assert payload["amount_minor"] == "100"
        assert payload["amount_minor_1"] == "200"
        break


async def test_a_short_row_becomes_missing_fields_not_a_crash(tmp_path: Path) -> None:
    connector = CsvUploadConnector()
    ctx = _context(
        tmp_path, payload=b"order_id,occurred_at,amount_minor,currency\nA-1,2026-05-01T10:00:00Z\n"
    )
    async for batch in connector.extract(ctx, ExtractRequest(resource="transactions")):
        reasons = connector.validate_record("transactions", batch.records[0])
        assert {r.flag.value for r in reasons} == {"missing_required"}
        break


async def test_a_trailing_blank_line_is_not_a_record(tmp_path: Path) -> None:
    """Almost every file ends with one. Each would otherwise be a quarantine entry."""
    connector = CsvUploadConnector()
    ctx = _context(tmp_path, payload=GOOD_CSV + b"\n\n")
    records = []
    async for batch in connector.extract(ctx, ExtractRequest(resource="transactions")):
        records.extend(batch.records)
    assert len(records) == 3


async def test_an_undecodable_byte_costs_one_field_not_the_file(tmp_path: Path) -> None:
    """A 200,000-row export should not be lost to one bad byte."""
    connector = CsvUploadConnector()
    ctx = _context(
        tmp_path,
        payload=b"order_id,occurred_at,amount_minor,currency\nA-\xff1,2026-05-01T10:00:00Z,1,GBP\n",
    )
    records = []
    async for batch in connector.extract(ctx, ExtractRequest(resource="transactions")):
        records.extend(batch.records)
    assert len(records) == 1


async def test_schema_inspection_reports_the_observed_header(tmp_path: Path) -> None:
    """Reporting the expected columns instead would hide schema drift."""
    connector = CsvUploadConnector()
    ctx = _context(tmp_path, payload=b"order_id,surprise_column\nA-1,x\n")
    schema = await connector.inspect_schema(ctx, "transactions")
    assert [f.name for f in schema.fields] == ["order_id", "surprise_column"]


# ---------------------------------------------------------------------------
# Resumption
# ---------------------------------------------------------------------------


async def test_resuming_from_a_checkpoint_skips_exactly_what_was_done(
    tmp_path: Path,
) -> None:
    """A worker restart must not repeat a row and must not skip one."""
    rows = b"order_id,occurred_at,amount_minor,currency\n" + b"".join(
        f"A-{i},2026-05-01T10:00:00Z,100,GBP\n".encode() for i in range(1200)
    )
    connector = CsvUploadConnector()
    ctx = _context(tmp_path, payload=rows)

    batches = []
    async for batch in connector.extract(ctx, ExtractRequest(resource="transactions")):
        batches.append(batch)

    assert len(batches) >= 3, "expected several batches for 1200 rows"
    first = batches[0]
    assert first.checkpoint is not None

    resumed: list[str] = []
    async for batch in connector.extract(
        ctx, ExtractRequest(resource="transactions", checkpoint=first.checkpoint)
    ):
        resumed.extend(r.source_record_id for r in batch.records)

    everything = [r.source_record_id for b in batches for r in b.records]
    recovered = [r.source_record_id for r in first.records] + resumed
    assert recovered == everything
    assert len(set(recovered)) == len(recovered), "resumption duplicated a row"


def test_the_connector_refuses_a_webhook_it_does_not_support(tmp_path: Path) -> None:
    """Declared unsupported must mean refused, never quietly accepted."""
    connector = CsvUploadConnector()
    ctx = _context(tmp_path)
    result = connector.verify_webhook(ctx, b"{}", {})
    assert not result.ok
    assert "does not accept webhooks" in result.reason
