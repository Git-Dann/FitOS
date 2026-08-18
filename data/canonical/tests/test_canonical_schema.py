"""The canonical contract, checked against a live ClickHouse.

These are the "canonical contract tests" the Phase C acceptance criteria name.
Every assertion here is a physical rule from docs/data-contracts.md §3, and each
one is checked against the server rather than against the DDL string — a DDL
string proves what we asked for, not what we got.

Skipped without a ClickHouse. `FITOS_REQUIRE_CLICKHOUSE=1` turns the skip into a
failure so the coverage cannot quietly disappear in CI.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Iterator

import pytest

from canonical.schema import DIMENSIONS, FACTS, QUARANTINE, all_statements

CLICKHOUSE_URL = os.environ.get("FITOS_CLICKHOUSE_URL", "http://127.0.0.1:8123/")
CLICKHOUSE_USER = os.environ.get("FITOS_CLICKHOUSE_USER", "fitos")
CLICKHOUSE_PASSWORD = os.environ.get("FITOS_CLICKHOUSE_PASSWORD", "fitos_local_only")
REQUIRE = bool(os.environ.get("FITOS_REQUIRE_CLICKHOUSE"))


def _query(sql: str, database: str = "fitos") -> str:
    params = urllib.parse.urlencode(
        {"user": CLICKHOUSE_USER, "password": CLICKHOUSE_PASSWORD, "database": database}
    )
    request = urllib.request.Request(f"{CLICKHOUSE_URL}?{params}", data=sql.encode())
    with urllib.request.urlopen(request, timeout=30) as response:
        return str(response.read().decode())


def _available() -> bool:
    try:
        _query("SELECT 1", database="default")
    except (urllib.error.URLError, OSError, urllib.error.HTTPError):
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _available() and not REQUIRE,
    reason="ClickHouse is not reachable; set FITOS_REQUIRE_CLICKHOUSE=1 to make this a failure",
)


@pytest.fixture(scope="module", autouse=True)
def schema() -> Iterator[None]:
    """Apply the canonical DDL once for the module."""
    if not _available():
        pytest.fail("FITOS_REQUIRE_CLICKHOUSE is set but ClickHouse is not reachable")
    for statement in all_statements():
        _query(statement, database="default")
    yield


# ---------------------------------------------------------------------------
# The physical rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fact", FACTS, ids=lambda f: f.name)
def test_every_fact_uses_replacingmergetree_on_ingested_at(fact: object) -> None:
    """RELEASE GATE support. This is what makes re-ingestion idempotent.

    Every other idempotency measure — content-addressed record ids, stable raw
    keys, delivery dedupe — ends here. A fact on a plain MergeTree appends on
    replay, and the whole chain fails one step from the finish.
    """
    engine = _query(
        f"SELECT engine_full FROM system.tables WHERE database='fitos' AND name='{fact.name}'"  # type: ignore[attr-defined]
    ).strip()
    assert "ReplacingMergeTree(ingested_at)" in engine, engine


@pytest.mark.parametrize("fact", FACTS, ids=lambda f: f.name)
def test_every_fact_is_partitioned_by_tenant_first(fact: object) -> None:
    """A partition that mixes tenants reads other people's data to answer yours."""
    key = _query(
        f"SELECT partition_key FROM system.tables WHERE database='fitos' AND name='{fact.name}'"  # type: ignore[attr-defined]
    ).strip()
    # ClickHouse renders a compound key parenthesised, so the leading "(" is
    # part of the answer rather than part of the column name.
    assert key.lstrip("(").startswith("organization_id"), key


@pytest.mark.parametrize("fact", FACTS, ids=lambda f: f.name)
def test_every_fact_sorts_by_tenant_first_and_never_by_a_generated_id(
    fact: object,
) -> None:
    """Ordering by event_id makes every real question a random scan."""
    sorting = _query(
        f"SELECT sorting_key FROM system.tables WHERE database='fitos' AND name='{fact.name}'"  # type: ignore[attr-defined]
    ).strip()
    assert sorting.startswith("organization_id"), sorting
    assert "event_id" not in sorting, sorting


@pytest.mark.parametrize("fact", FACTS, ids=lambda f: f.name)
def test_every_fact_has_an_explicit_ttl(fact: object) -> None:
    """A table with no TTL grows until somebody notices the bill."""
    expression = _query(
        f"SELECT engine_full FROM system.tables WHERE database='fitos' AND name='{fact.name}'"  # type: ignore[attr-defined]
    )
    assert "TTL" in expression, f"{fact.name} has no TTL"  # type: ignore[attr-defined]


@pytest.mark.parametrize("fact", FACTS, ids=lambda f: f.name)
def test_every_fact_carries_lineage(fact: object) -> None:
    """A canonical row that cannot name its raw object cannot be evidence.

    And a gap without evidence is not allowed to exist, so a fact missing
    lineage is a fact that can never raise one.
    """
    columns = set(
        _query(
            f"SELECT name FROM system.columns WHERE database='fitos' AND table='{fact.name}'"  # type: ignore[attr-defined]
        ).split()
    )
    for required in ("organization_id", "lineage_ref", "ingested_at"):
        assert required in columns, f"{fact.name} has no {required}"  # type: ignore[attr-defined]

    # A mapped fact must name the mapping version that produced it. A derived
    # fact has none — it is computed from other canonical facts — and carries
    # metric_version instead, which is what a gap references.
    if fact.derived:  # type: ignore[attr-defined]
        assert "metric_version" in columns, f"{fact.name} is derived but names no version"  # type: ignore[attr-defined]
    else:
        assert "mapping_version" in columns, f"{fact.name} has no mapping_version"  # type: ignore[attr-defined]


@pytest.mark.parametrize("fact", FACTS, ids=lambda f: f.name)
def test_no_fact_stores_money_as_a_float(fact: object) -> None:
    """Binary floating point cannot represent 19.99.

    The error is invisible per row and compounds over a million of them, which
    is how a revenue figure ends up wrong by an amount nobody can explain.
    """
    rows = _query(
        f"SELECT name, type FROM system.columns WHERE database='fitos' AND table='{fact.name}'"  # type: ignore[attr-defined]
    ).strip()
    for line in rows.splitlines():
        name, _, type_ = line.partition("\t")
        if any(token in name for token in ("amount", "cost", "price", "value")):
            assert "Float" not in type_, f"{fact.name}.{name} is {type_}"  # type: ignore[attr-defined]


def test_the_three_timestamps_are_distinct_columns() -> None:
    """Collapsing them makes a late source indistinguishable from a broken one.

    occurred_at drives analysis, ingested_at drives freshness, received_at
    separates a slow source from a slow pipeline.
    """
    columns = set(
        _query(
            "SELECT name FROM system.columns WHERE database='fitos' AND table='fact_transaction'"
        ).split()
    )
    assert {"occurred_at", "ingested_at", "received_at"} <= columns


# ---------------------------------------------------------------------------
# Idempotency, demonstrated rather than asserted
# ---------------------------------------------------------------------------


def test_reingesting_the_same_record_yields_one_row() -> None:
    """RELEASE GATE. The same extract twice must not double the canonical layer.

    Written twice with the same natural key and collapsed with FINAL, which is
    what a query through the governed layer does.
    """
    org = uuid.uuid4()
    values = (
        f"('{org}', 'csv_upload', '{uuid.uuid4()}', 'REC-1', 'raw/x', 1, "
        "'2026-05-01 10:00:00.000', '2026-05-01 10:00:01.000', NULL, [], "
        "'T-1', 'NS-014', 'store', NULL, NULL, 1250, 'GBP', 1)"
    )
    insert = (
        "INSERT INTO fitos.fact_transaction (organization_id, source_key, "
        "source_connection_id, source_record_id, lineage_ref, mapping_version, "
        "occurred_at, ingested_at, received_at, data_quality_flags, transaction_id, "
        "location_id, channel_id, campaign_id, anonymous_subject_id, amount_minor, "
        "currency, line_count) VALUES "
    )

    _query(insert + values)
    _query(insert + values)

    collapsed = _query(
        f"SELECT count() FROM fitos.fact_transaction FINAL WHERE organization_id = '{org}'"
    ).strip()
    assert collapsed == "1", f"a replay produced {collapsed} rows"


def test_a_later_ingestion_of_the_same_record_wins() -> None:
    """A correction re-runs the same record and the newer version must survive.

    This is what makes "corrections happen forward" work at the storage layer:
    the fix is a re-ingestion, not an UPDATE.
    """
    org = uuid.uuid4()
    insert = (
        "INSERT INTO fitos.fact_transaction (organization_id, source_key, "
        "source_connection_id, source_record_id, lineage_ref, mapping_version, "
        "occurred_at, ingested_at, received_at, data_quality_flags, transaction_id, "
        "location_id, channel_id, campaign_id, anonymous_subject_id, amount_minor, "
        "currency, line_count) VALUES "
    )
    connection = uuid.uuid4()
    base = (
        f"('{org}', 'csv_upload', '{connection}', 'REC-2', 'raw/y', {{version}}, "
        "'2026-05-01 10:00:00.000', '{ingested}', NULL, [], "
        "'T-2', 'NS-014', 'store', NULL, NULL, {amount}, 'GBP', 1)"
    )

    _query(insert + base.format(version=1, ingested="2026-05-01 10:00:01.000", amount=1000))
    _query(insert + base.format(version=2, ingested="2026-05-02 09:00:00.000", amount=1250))

    amount = _query(
        "SELECT amount_minor FROM fitos.fact_transaction FINAL "
        f"WHERE organization_id = '{org}' AND source_record_id = 'REC-2'"
    ).strip()
    assert amount == "1250", f"the correction did not win: {amount}"


def test_two_tenants_with_the_same_source_record_id_stay_separate() -> None:
    """Source ids are only unique within a source, and two tenants share sources.

    organization_id leads the sort key precisely so the same 'ORDER-1' from two
    retailers does not collapse into one row.
    """
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    insert = (
        "INSERT INTO fitos.fact_transaction (organization_id, source_key, "
        "source_connection_id, source_record_id, lineage_ref, mapping_version, "
        "occurred_at, ingested_at, received_at, data_quality_flags, transaction_id, "
        "location_id, channel_id, campaign_id, anonymous_subject_id, amount_minor, "
        "currency, line_count) VALUES "
    )
    for org in (org_a, org_b):
        _query(
            insert + f"('{org}', 'csv_upload', '{uuid.uuid4()}', 'ORDER-1', 'raw/z', 1, "
            "'2026-05-01 10:00:00.000', '2026-05-01 10:00:01.000', NULL, [], "
            "'T-3', 'NS-014', 'store', NULL, NULL, 500, 'GBP', 1)"
        )

    for org in (org_a, org_b):
        count = _query(
            "SELECT count() FROM fitos.fact_transaction FINAL "
            f"WHERE organization_id = '{org}' AND source_record_id = 'ORDER-1'"
        ).strip()
        assert count == "1", f"{org} sees {count} rows"


# ---------------------------------------------------------------------------
# Dimensions and quarantine
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dimension", DIMENSIONS, ids=lambda d: d.name)
def test_every_dimension_is_tenant_scoped(dimension: object) -> None:
    sorting = _query(
        f"SELECT sorting_key FROM system.tables WHERE database='fitos' AND name='{dimension.name}'"  # type: ignore[attr-defined]
    ).strip()
    assert sorting.startswith("organization_id"), sorting


def test_slowly_changing_dimensions_carry_validity_windows() -> None:
    """Last year's margin must use last year's cost price.

    Without valid_from/valid_to, a cost correction silently rewrites every
    historical margin figure that dimension ever contributed to.
    """
    for name in ("dim_location", "dim_product_variant"):
        columns = set(
            _query(
                f"SELECT name FROM system.columns WHERE database='fitos' AND table='{name}'"
            ).split()
        )
        assert {"valid_from", "valid_to"} <= columns, name


def test_quarantine_reaches_the_analytics_store() -> None:
    """So data_completeness is computable from the same store as everything else.

    A rejection count that lives only in PostgreSQL cannot be joined to the
    metric it is supposed to suppress.
    """
    columns = set(
        _query(
            f"SELECT name FROM system.columns WHERE database='fitos' AND table='{QUARANTINE.name}'"
        ).split()
    )
    assert {"reason_flags", "lineage_ref", "mapping_version", "run_id"} <= columns


def test_the_declared_tables_all_exist() -> None:
    """Guards the guard: a parametrised suite over an empty list passes."""
    present = set(_query("SELECT name FROM system.tables WHERE database='fitos'").split())
    expected = (
        {fact.name for fact in FACTS}
        | {dimension.name for dimension in DIMENSIONS}
        | {QUARANTINE.name}
    )
    assert expected <= present, f"missing: {sorted(expected - present)}"
    assert len(expected) >= 12, "the schema shrank; the parametrised tests cover less than before"
