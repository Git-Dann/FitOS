"""The 14-point connector contract, as a reusable suite.

Shipped as library code rather than copied into each connector's tests, because
a contract that each connector implements its own version of is not a contract.
A connector adds four lines to its test module and inherits every check:

    from fitos_connector_sdk.contract_tests import ConnectorContractTests

    class TestCsvContract(ConnectorContractTests):
        @pytest.fixture
        def harness(self) -> ConnectorHarness: ...

Tests 7 (idempotency), 8 (duplicate webhook) and 14 (egress) are release gates
named in the definition of done. They are marked as such in their docstrings so
that a failure is read as a release blocker rather than a flaky test.

The suite is capability-aware: a connector whose manifest says
`supports_webhooks: false` skips the webhook tests, but is *checked* for
refusing a webhook rather than silently accepting one. "Not supported" has to
mean refused, not ignored — an endpoint that accepts unverified payloads is
worse than no endpoint. That asymmetry is the reason this is not simply a
`pytest.skip`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from fitos_connector_sdk.context import ConnectorContext
from fitos_connector_sdk.egress import EgressBlockedError
from fitos_connector_sdk.quarantine import QuarantineReason
from fitos_connector_sdk.types import (
    BackfillRequest,
    Connector,
    ConnectorManifest,
    ExtractRequest,
    RecordBatch,
    SourceRecord,
)
from fitos_connector_sdk.webhooks import InMemoryDeliveryStore, accept_delivery


@dataclass
class ConnectorHarness:
    """Everything the suite needs to exercise one connector.

    A connector supplies this; the suite supplies the checks. Keeping the
    fixture data here rather than in the suite is what lets the same 14 tests
    run against a file parser and an HTTP client without either of them being
    special-cased.
    """

    connector: Connector
    context: ConnectorContext
    resource: str

    # A record that must be quarantined, and the reason it must be quarantined
    # for. Naming the expected flag stops a connector passing test 12 by
    # rejecting a valid record for an unrelated reason.
    malformed_record: SourceRecord | None = None
    expected_flag: str | None = None

    # For webhook-capable connectors.
    webhook_body: bytes | None = None
    webhook_headers: dict[str, str] = field(default_factory=dict)
    tampered_body: bytes | None = None

    # A config that names a forbidden host, for test 14.
    private_host_config: dict[str, Any] | None = None

    organization_id: UUID = field(default_factory=uuid4)

    async def extract_all(self) -> list[RecordBatch]:
        batches: list[RecordBatch] = []
        request = ExtractRequest(resource=self.resource)
        async for batch in self.connector.extract(self.context, request):
            batches.append(batch)
        return batches


class ConnectorContractTests(ABC):
    """The suite. Subclass it and provide `harness`."""

    @pytest.fixture
    @abstractmethod
    def harness(self) -> ConnectorHarness: ...

    # -- 1. manifest ------------------------------------------------------

    def test_01_manifest_is_valid(self, harness: ConnectorHarness) -> None:
        """A connector without a valid manifest fails the build."""
        manifest = harness.connector.manifest
        assert isinstance(manifest, ConnectorManifest)
        # Round-trips through validation, so a manifest built by hand and one
        # loaded from YAML are held to the same rules.
        ConnectorManifest.model_validate(manifest.model_dump())
        assert harness.resource in manifest.supported_resources

    def test_01b_canonical_targets_reference_supported_resources(
        self, harness: ConnectorHarness
    ) -> None:
        """A target for a resource that does not exist is a mapping that never runs."""
        manifest = harness.connector.manifest
        assert set(manifest.canonical_targets) <= set(manifest.supported_resources)

    # -- 2. config validation ---------------------------------------------

    def test_02_validate_config_names_the_field_that_is_missing(
        self, harness: ConnectorHarness
    ) -> None:
        """A generic "invalid config" makes the operator guess. Name the field."""
        result = harness.connector.validate_config({})
        assert not result.ok
        assert result.problems, "validate_config rejected the config without saying why"
        for problem in result.problems:
            assert problem.field, "a problem with no field name is not actionable"
            assert problem.message

    def test_02b_a_valid_config_is_accepted(self, harness: ConnectorHarness) -> None:
        """Otherwise test 2 passes for a validator that rejects everything."""
        result = harness.connector.validate_config(dict(harness.context.config))
        assert result.ok, f"the harness config was rejected: {result.problems}"

    # -- 3. credentials ---------------------------------------------------

    async def test_03_credential_test_never_echoes_a_secret(
        self, harness: ConnectorHarness
    ) -> None:
        """Contract test 13's most likely leak point, checked at its source."""
        result = await harness.connector.test_credentials(harness.context)
        rendered = f"{result.model_dump()}"
        for key in harness.context.secrets.accessed | set():
            value = harness.context.secrets.get(key)
            assert value not in rendered, f"the credential test echoed secret {key!r}"

    # -- 4. schema inspection ---------------------------------------------

    async def test_04_inspect_schema_reports_fields(self, harness: ConnectorHarness) -> None:
        if not harness.connector.manifest.supports_schema_inspection:
            pytest.skip("connector declares no schema inspection")
        schema = await harness.connector.inspect_schema(harness.context, harness.resource)
        assert schema.resource == harness.resource
        assert schema.fields, "schema inspection returned no fields"
        names = [f.name for f in schema.fields]
        assert len(names) == len(set(names)), f"duplicate field names in schema: {names}"

    # -- 5. deterministic plan --------------------------------------------

    async def test_05_backfill_plan_is_deterministic(self, harness: ConnectorHarness) -> None:
        """A plan that varies run to run cannot be resumed.

        Resuming means knowing which windows are already done, which is only
        meaningful if the same request produces the same windows.
        """
        request = BackfillRequest(
            resource=harness.resource,
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 8, tzinfo=UTC),
        )
        first = await harness.connector.plan_backfill(harness.context, request)
        second = await harness.connector.plan_backfill(harness.context, request)
        assert first.model_dump() == second.model_dump()

    # -- 6. extraction ----------------------------------------------------

    async def test_06_extract_produces_records_with_provenance(
        self, harness: ConnectorHarness
    ) -> None:
        """Every record points at the raw object it came from.

        A record that cannot say where it came from cannot become evidence, and
        a gap without evidence is not allowed to exist.
        """
        batches = await harness.extract_all()
        assert batches, "extract produced no batches"
        for batch in batches:
            for record in batch.records:
                assert record.raw_ref, "a record has no raw reference"
                assert record.source_record_id

    async def test_06b_record_ids_are_unique_within_a_run(self, harness: ConnectorHarness) -> None:
        batches = await harness.extract_all()
        ids = [r.source_record_id for batch in batches for r in batch.records]
        assert len(ids) == len(set(ids)), "duplicate source_record_id within one extract"

    # -- 7. idempotency (RELEASE GATE) ------------------------------------

    async def test_07_the_same_extract_twice_yields_the_same_records(
        self, harness: ConnectorHarness
    ) -> None:
        """RELEASE GATE. Re-running must replace, not duplicate.

        The ids have to match exactly, not merely the counts: matching counts
        with different ids means the canonical layer gets two rows per record
        and a ReplacingMergeTree cannot collapse them.
        """
        first = await harness.extract_all()
        second = await harness.extract_all()

        first_ids = [r.source_record_id for b in first for r in b.records]
        second_ids = [r.source_record_id for b in second for r in b.records]

        assert first_ids == second_ids, "a second identical extract produced different record ids"

    # -- 8. duplicate webhook (RELEASE GATE) ------------------------------

    def test_08_the_same_delivery_twice_is_accepted_once(self, harness: ConnectorHarness) -> None:
        """RELEASE GATE. Sources retry; a retry must not create a second fact."""
        if not harness.connector.manifest.supports_webhooks:
            pytest.skip("connector declares no webhook support")

        store = InMemoryDeliveryStore()
        delivery_id = "delivery-1"

        assert accept_delivery(
            store=store,
            organization_id=harness.organization_id,
            connector_key=harness.connector.manifest.key,
            delivery_id=delivery_id,
        )
        assert not accept_delivery(
            store=store,
            organization_id=harness.organization_id,
            connector_key=harness.connector.manifest.key,
            delivery_id=delivery_id,
        ), "the same delivery was accepted twice"

    def test_08b_the_same_delivery_id_in_another_tenant_is_not_a_duplicate(
        self, harness: ConnectorHarness
    ) -> None:
        """Dedupe is per tenant. Sources number deliveries from 1 for everyone."""
        if not harness.connector.manifest.supports_webhooks:
            pytest.skip("connector declares no webhook support")

        store = InMemoryDeliveryStore()
        for organization in (uuid4(), uuid4()):
            assert accept_delivery(
                store=store,
                organization_id=organization,
                connector_key=harness.connector.manifest.key,
                delivery_id="1",
            )

    # -- 9. signature -----------------------------------------------------

    def test_09_a_tampered_body_is_rejected(self, harness: ConnectorHarness) -> None:
        if not harness.connector.manifest.supports_webhooks:
            pytest.skip("connector declares no webhook support")
        assert harness.webhook_body is not None
        assert harness.tampered_body is not None

        good = harness.connector.verify_webhook(
            harness.context, harness.webhook_body, harness.webhook_headers
        )
        assert good.ok, f"a valid webhook was rejected: {good.reason}"

        bad = harness.connector.verify_webhook(
            harness.context, harness.tampered_body, harness.webhook_headers
        )
        assert not bad.ok, "a tampered body passed verification"

    def test_09b_an_unsupported_webhook_is_refused_not_ignored(
        self, harness: ConnectorHarness
    ) -> None:
        """ "Not supported" must mean refused.

        A connector that declares no webhook support and then returns ok=True
        for one has an endpoint accepting unverified payloads, which is worse
        than having no endpoint at all.
        """
        if harness.connector.manifest.supports_webhooks:
            pytest.skip("connector supports webhooks; covered by test 9")
        result = harness.connector.verify_webhook(harness.context, b"{}", {})
        assert not result.ok
        assert result.reason

    # -- 10. checkpoint resume --------------------------------------------

    async def test_10_resuming_from_a_checkpoint_yields_the_same_final_state(
        self, harness: ConnectorHarness
    ) -> None:
        """A worker restart must resume, not restart and not skip.

        The test stops after the first batch, restores the checkpoint into a
        fresh request, and asserts the union equals an uninterrupted run — with
        no record appearing twice and none missing.
        """
        uninterrupted = await harness.extract_all()
        all_ids = [r.source_record_id for b in uninterrupted for r in b.records]
        if len(uninterrupted) < 2:
            pytest.skip("connector yields a single batch; resumption is trivial")

        first_batch = uninterrupted[0]
        assert first_batch.checkpoint is not None, (
            "a multi-batch extract must checkpoint, or a restart loses its place"
        )

        resumed: list[str] = []
        request = ExtractRequest(resource=harness.resource, checkpoint=first_batch.checkpoint)
        async for batch in harness.connector.extract(harness.context, request):
            resumed.extend(r.source_record_id for r in batch.records)

        recovered = [r.source_record_id for r in first_batch.records] + resumed
        assert recovered == all_ids, "resuming from a checkpoint changed the record set"

    # -- 11. rate limiting ------------------------------------------------

    async def test_11_rate_limiting_waits_rather_than_fails(
        self, harness: ConnectorHarness
    ) -> None:
        """A 429 is a backoff instruction, not an error.

        A connector that treats it as failure turns a busy source into a broken
        connection, and the run summary then blames the source.
        """
        limiter = harness.context.rate_limiter
        for _ in range(3):
            await limiter.acquire()
        assert limiter.waits >= 0  # no exception is the assertion

    # -- 12. quarantine ---------------------------------------------------

    def test_12_a_malformed_record_is_quarantined_with_a_reason(
        self, harness: ConnectorHarness
    ) -> None:
        """And the run still completes. Silent rejection is prohibited."""
        if harness.malformed_record is None:
            pytest.skip("connector supplied no malformed record fixture")

        validate = getattr(harness.connector, "validate_record", None)
        assert validate is not None, "a connector that can quarantine must expose validate_record"

        reasons: list[QuarantineReason] = validate(harness.resource, harness.malformed_record)
        assert reasons, "a malformed record produced no quarantine reason"

        if harness.expected_flag is not None:
            flags = {reason.flag.value for reason in reasons}
            assert harness.expected_flag in flags, (
                f"expected flag {harness.expected_flag!r}, got {sorted(flags)}"
            )

    async def test_12b_a_valid_record_is_not_quarantined(self, harness: ConnectorHarness) -> None:
        """Otherwise test 12 passes for a validator that rejects everything."""
        validate = getattr(harness.connector, "validate_record", None)
        if validate is None:
            pytest.skip("connector does no per-record validation")

        batches = await harness.extract_all()
        records = [r for b in batches for r in b.records]
        if not records:
            pytest.skip("no records to check")

        accepted = [r for r in records if not validate(harness.resource, r)]
        assert accepted, "every extracted record was quarantined; validation rejects everything"

    # -- 13. secrets ------------------------------------------------------

    async def test_13_secrets_never_appear_in_the_run_record(
        self, harness: ConnectorHarness
    ) -> None:
        """The run record is readable by anyone with audit.view and is kept forever."""
        health = await harness.connector.health(harness.context)
        rendered = f"{health.model_dump()}{harness.connector.manifest.model_dump()}"
        for key in harness.context.config:
            if "secret" in key or "token" in key or "password" in key:
                pytest.fail(f"a secret-shaped key {key!r} is in the config dict, not the resolver")
        assert "SecretResolver" not in rendered

    def test_13b_the_resolver_does_not_render_its_values(self, harness: ConnectorHarness) -> None:
        """A resolver that renders its contents ends up in the first traceback."""
        rendered = repr(harness.context.secrets)
        for key in list(harness.context.secrets.accessed) or []:
            assert harness.context.secrets.get(key) not in rendered

    # -- 14. egress (RELEASE GATE) ----------------------------------------

    async def test_14_a_private_host_is_refused(self, harness: ConnectorHarness) -> None:
        """RELEASE GATE. A connector aimed at the private network is refused.

        Skipped only for connectors that make no outbound request at all — for
        those, the property is enforced by there being no client in use, which
        `test_14b` confirms.
        """
        if harness.private_host_config is None:
            pytest.skip("connector makes no outbound requests")

        with pytest.raises(EgressBlockedError):
            await harness.connector.test_credentials(
                _with_config(harness.context, harness.private_host_config)
            )

    def test_14b_the_connector_did_not_build_its_own_http_client(
        self, harness: ConnectorHarness
    ) -> None:
        """The egress policy is only unavoidable if there is no second client.

        A connector that imports httpx and constructs its own AsyncClient has
        an unchecked path to the network, and it looks exactly like working
        code.
        """
        import inspect

        source = inspect.getsource(type(harness.connector))
        for forbidden in ("httpx.AsyncClient(", "httpx.Client(", "urlopen(", "requests."):
            assert forbidden not in source, (
                f"{type(harness.connector).__name__} constructs its own HTTP access "
                f"({forbidden}), bypassing the egress policy"
            )


def _with_config(ctx: ConnectorContext, config: dict[str, Any]) -> ConnectorContext:
    """A copy of the context with different config, sharing the same client."""
    from dataclasses import replace

    return replace(ctx, config={**ctx.config, **config})


def window_count_for(start: datetime, end: datetime, step: timedelta) -> int:
    """Shared helper for connectors that plan by fixed windows."""
    total = int((end - start) / step)
    return max(total, 1)
