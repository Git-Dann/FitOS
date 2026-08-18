"""The canonical ClickHouse layer, as data.

Held as Python rather than loose `.sql` files so the physical rules from
docs/data-contracts.md §3 can be asserted rather than hoped for. Every fact
table here is checked by `test_canonical_schema.py` against a live ClickHouse,
because these four rules are the difference between a warehouse that answers in
milliseconds and one that answers eventually:

**`ReplacingMergeTree(ingested_at)` keyed on the source natural key.** This is
what makes re-ingestion idempotent at the storage layer. A duplicate webhook or
a connector replay writes the same key again and the engine collapses it. Note
what it is *not* keyed on: `event_id`. Keying on a generated id would make every
replay a new row, and the whole idempotency chain — content-addressed record
ids, stable raw keys — would end here, one step from the finish.

**Partition by `(organization_id, toYYYYMM(occurred_at))`.** Tenant first,
because every query is tenant-scoped and a partition that mixes tenants reads
other people's data to answer yours. Month second, because retention and tiering
are monthly operations.

**Order by the query pattern, never by the id.** `(organization_id,
location_id, occurred_at)` matches "this location, this period", which is what
the gap ledger actually asks. Ordering by `event_id` would be a random scan for
every question anyone has.

**Explicit TTL per fact.** A table with no TTL is a table that grows until
somebody notices the bill.

`occurred_at` is deliberately in the sort key and the partition key while
`ingested_at` is the replacing version. They are different questions —
`occurred_at` is when it happened in the world, `ingested_at` is when we learned
about it — and collapsing them makes late-arriving data indistinguishable from a
broken connector.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FactTable:
    """One canonical fact, with the physical rules it must satisfy."""

    name: str
    grain: str
    columns: tuple[tuple[str, str], ...]
    order_by: tuple[str, ...]
    version_column: str = "ingested_at"
    partition_by: str = "(organization_id, toYYYYMM(occurred_at))"
    ttl_days: int = 2555  # seven years by default; overridden per fact
    ttl_column: str = "occurred_at"
    # A derived fact is computed from other canonical facts rather than mapped
    # from a source record, so it has no mapping version to carry. Its lineage
    # is the metric version plus the facts it was computed from. Flagged rather
    # than special-cased in the tests, so "why is this one different" has an
    # answer in the schema instead of in an exception list.
    derived: bool = False

    def create_sql(self, database: str = "fitos") -> str:
        columns = ",\n  ".join(f"{name} {type_}" for name, type_ in self.columns)
        order = ", ".join(self.order_by)
        return (
            f"CREATE TABLE IF NOT EXISTS {database}.{self.name} (\n  {columns}\n)\n"
            f"ENGINE = ReplacingMergeTree({self.version_column})\n"
            f"PARTITION BY {self.partition_by}\n"
            f"ORDER BY ({order})\n"
            # toDateTime, because ClickHouse refuses a DateTime64 in a TTL
            # expression: "TTL expression result column should have DateTime or
            # Date type". The millisecond precision matters for ordering and
            # for lineage; it is irrelevant to a retention boundary measured in
            # years, so the cast loses nothing.
            f"TTL toDateTime({self.ttl_column}) + INTERVAL {self.ttl_days} DAY\n"
            f"SETTINGS index_granularity = 8192"
        )


@dataclass(frozen=True)
class DimensionTable:
    """A dimension. Type 2 where history matters, type 1 elsewhere."""

    name: str
    columns: tuple[tuple[str, str], ...]
    order_by: tuple[str, ...]
    slowly_changing: bool = False

    def create_sql(self, database: str = "fitos") -> str:
        columns = ",\n  ".join(f"{name} {type_}" for name, type_ in self.columns)
        order = ", ".join(self.order_by)
        # Dimensions are replaced by natural key rather than appended, so a
        # corrected attribute does not produce a second row that joins twice.
        return (
            f"CREATE TABLE IF NOT EXISTS {database}.{self.name} (\n  {columns}\n)\n"
            f"ENGINE = ReplacingMergeTree(updated_at)\n"
            f"ORDER BY ({order})\n"
            f"SETTINGS index_granularity = 8192"
        )


# Columns every fact carries. Lineage is not optional: a canonical row that
# cannot name the raw object and mapping version that produced it cannot be
# evidence, and a gap without evidence is not allowed to exist.
LINEAGE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("organization_id", "UUID"),
    ("source_key", "LowCardinality(String)"),
    ("source_connection_id", "UUID"),
    ("source_record_id", "String"),
    ("lineage_ref", "String"),
    ("mapping_version", "UInt32"),
    ("occurred_at", "DateTime64(3, 'UTC')"),
    ("ingested_at", "DateTime64(3, 'UTC')"),
    ("received_at", "Nullable(DateTime64(3, 'UTC'))"),
    ("data_quality_flags", "Array(LowCardinality(String))"),
)


FACTS: tuple[FactTable, ...] = (
    FactTable(
        name="fact_transaction",
        grain="one order",
        columns=(
            *LINEAGE_COLUMNS,
            ("transaction_id", "String"),
            ("location_id", "LowCardinality(String)"),
            ("channel_id", "LowCardinality(String)"),
            ("campaign_id", "LowCardinality(Nullable(String))"),
            ("anonymous_subject_id", "Nullable(String)"),
            # Money is minor units plus an ISO code. Never a float: binary
            # floating point cannot represent 19.99, and the error compounds
            # over a million rows.
            ("amount_minor", "Int64"),
            ("currency", "FixedString(3)"),
            ("line_count", "UInt32"),
        ),
        # (tenant, location, time) is "this shop, this period", which is what
        # the ledger asks. The source key is last so the replacing engine can
        # still collapse duplicates.
        order_by=(
            "organization_id",
            "location_id",
            "occurred_at",
            "source_key",
            "source_record_id",
        ),
        ttl_days=2555,
    ),
    FactTable(
        name="fact_transaction_line",
        grain="one line",
        columns=(
            *LINEAGE_COLUMNS,
            ("transaction_id", "String"),
            ("line_number", "UInt32"),
            ("location_id", "LowCardinality(String)"),
            ("product_variant_id", "String"),
            ("quantity", "Decimal(18, 4)"),
            ("unit_amount_minor", "Int64"),
            # Carried so margin is computable without a join to a dimension
            # whose value changes over time. The type 2 dimension still records
            # the history; this is the cost as it was on the day.
            ("unit_cost_minor", "Nullable(Int64)"),
            ("currency", "FixedString(3)"),
        ),
        order_by=(
            "organization_id",
            "location_id",
            "occurred_at",
            "transaction_id",
            "line_number",
        ),
        ttl_days=2555,
    ),
    FactTable(
        name="fact_inventory_snapshot",
        grain="variant x location x snapshot",
        columns=(
            *LINEAGE_COLUMNS,
            ("location_id", "LowCardinality(String)"),
            ("product_variant_id", "String"),
            # What the system believes. Pairs with fact_stock_check, which is
            # what a person actually saw; the difference is the Stock Truth Gap.
            ("system_quantity", "Decimal(18, 4)"),
        ),
        order_by=(
            "organization_id",
            "location_id",
            "product_variant_id",
            "occurred_at",
        ),
        ttl_days=1095,
    ),
    FactTable(
        name="fact_stock_check",
        grain="one manual check",
        columns=(
            *LINEAGE_COLUMNS,
            ("check_id", "String"),
            ("location_id", "LowCardinality(String)"),
            ("product_variant_id", "String"),
            ("staff_member_id", "Nullable(String)"),
            ("observed_quantity", "Decimal(18, 4)"),
        ),
        order_by=(
            "organization_id",
            "location_id",
            "product_variant_id",
            "occurred_at",
            "check_id",
        ),
        ttl_days=1095,
    ),
    FactTable(
        name="fact_footfall_observation",
        grain="counter x 15 min",
        columns=(
            *LINEAGE_COLUMNS,
            ("location_id", "LowCardinality(String)"),
            ("counter_id", "LowCardinality(String)"),
            # An interval, not an instant. A footfall count with no declared
            # window cannot be compared against anything, and the expected
            # cadence is what makes data_freshness meaningful.
            ("interval_seconds", "UInt32"),
            ("visitor_count", "UInt32"),
        ),
        order_by=("organization_id", "location_id", "occurred_at", "counter_id"),
        ttl_days=1095,
    ),
    FactTable(
        name="fact_service_request",
        grain="one request",
        columns=(
            *LINEAGE_COLUMNS,
            ("request_id", "String"),
            ("location_id", "LowCardinality(String)"),
            ("product_variant_id", "Nullable(String)"),
            ("anonymous_subject_id", "Nullable(String)"),
            ("request_type", "LowCardinality(String)"),
            # An unmet request carries its reason. "Unmet" with no reason is a
            # number nobody can act on, which is the whole point of the metric.
            ("fulfilment_status", "LowCardinality(String)"),
            ("unmet_reason", "LowCardinality(Nullable(String))"),
        ),
        order_by=("organization_id", "location_id", "occurred_at", "request_id"),
        ttl_days=1095,
    ),
    FactTable(
        name="fact_metric_observation",
        grain="metric x grain x window",
        columns=(
            ("organization_id", "UUID"),
            ("metric_key", "LowCardinality(String)"),
            # The version is part of the key. A metric whose formula changed
            # must not silently overwrite the values the old formula produced,
            # because a gap references the version that raised it.
            ("metric_version", "UInt32"),
            ("grain", "LowCardinality(String)"),
            ("dimension_key", "String"),
            ("window_start", "DateTime64(3, 'UTC')"),
            ("window_end", "DateTime64(3, 'UTC')"),
            ("value", "Nullable(Decimal(38, 10))"),
            ("denominator", "Nullable(Decimal(38, 10))"),
            ("occurred_at", "DateTime64(3, 'UTC')"),
            ("ingested_at", "DateTime64(3, 'UTC')"),
            ("lineage_ref", "String"),
            ("data_quality_flags", "Array(LowCardinality(String))"),
        ),
        order_by=(
            "organization_id",
            "metric_key",
            "metric_version",
            "grain",
            "dimension_key",
            "window_start",
        ),
        ttl_days=1095,
        derived=True,
    ),
)


DIMENSIONS: tuple[DimensionTable, ...] = (
    DimensionTable(
        name="dim_location",
        columns=(
            ("organization_id", "UUID"),
            ("location_id", "LowCardinality(String)"),
            ("name", "String"),
            ("region", "LowCardinality(Nullable(String))"),
            ("floor_area_sqm", "Nullable(Decimal(18, 2))"),
            ("valid_from", "DateTime64(3, 'UTC')"),
            ("valid_to", "Nullable(DateTime64(3, 'UTC'))"),
            ("updated_at", "DateTime64(3, 'UTC')"),
        ),
        # Type 2: floor area changes and historical analysis must use the value
        # that applied at the time, not today's.
        order_by=("organization_id", "location_id", "valid_from"),
        slowly_changing=True,
    ),
    DimensionTable(
        name="dim_product_variant",
        columns=(
            ("organization_id", "UUID"),
            ("product_variant_id", "String"),
            ("product_id", "String"),
            ("sku", "String"),
            ("name", "String"),
            ("cost_price_minor", "Nullable(Int64)"),
            ("currency", "Nullable(FixedString(3))"),
            ("valid_from", "DateTime64(3, 'UTC')"),
            ("valid_to", "Nullable(DateTime64(3, 'UTC'))"),
            ("updated_at", "DateTime64(3, 'UTC')"),
        ),
        # Type 2: cost price drives margin, and last year's margin must be
        # computed with last year's cost.
        order_by=("organization_id", "product_variant_id", "valid_from"),
        slowly_changing=True,
    ),
    DimensionTable(
        name="dim_channel",
        columns=(
            ("organization_id", "UUID"),
            ("channel_id", "LowCardinality(String)"),
            ("name", "String"),
            ("kind", "LowCardinality(String)"),
            ("updated_at", "DateTime64(3, 'UTC')"),
        ),
        order_by=("organization_id", "channel_id"),
    ),
    DimensionTable(
        name="dim_source",
        columns=(
            ("organization_id", "UUID"),
            ("source_key", "LowCardinality(String)"),
            ("connector_version", "UInt32"),
            ("name", "String"),
            ("expected_cadence_seconds", "Nullable(UInt32)"),
            ("updated_at", "DateTime64(3, 'UTC')"),
        ),
        order_by=("organization_id", "source_key"),
    ),
)


@dataclass(frozen=True)
class Quarantine:
    """Rejected records reach ClickHouse too.

    So `data_completeness` can be computed from the same store as everything
    else. A rejection count that lives only in PostgreSQL cannot be joined to
    the metric it should suppress.
    """

    name: str = "quarantine_record"
    columns: tuple[tuple[str, str], ...] = field(
        default_factory=lambda: (
            ("organization_id", "UUID"),
            ("run_id", "UUID"),
            ("source_key", "LowCardinality(String)"),
            ("resource", "LowCardinality(String)"),
            ("source_record_id", "String"),
            ("lineage_ref", "String"),
            ("mapping_version", "UInt32"),
            ("reason_flags", "Array(LowCardinality(String))"),
            ("occurred_at", "DateTime64(3, 'UTC')"),
            ("ingested_at", "DateTime64(3, 'UTC')"),
        )
    )

    def create_sql(self, database: str = "fitos") -> str:
        columns = ",\n  ".join(f"{name} {type_}" for name, type_ in self.columns)
        return (
            f"CREATE TABLE IF NOT EXISTS {database}.{self.name} (\n  {columns}\n)\n"
            f"ENGINE = ReplacingMergeTree(ingested_at)\n"
            f"PARTITION BY (organization_id, toYYYYMM(occurred_at))\n"
            f"ORDER BY (organization_id, source_key, occurred_at, source_record_id)\n"
            f"TTL toDateTime(occurred_at) + INTERVAL 365 DAY"
        )


QUARANTINE = Quarantine()


def all_statements(database: str = "fitos") -> list[str]:
    """Every DDL statement, in dependency order."""
    statements = [f"CREATE DATABASE IF NOT EXISTS {database}"]
    statements.extend(dimension.create_sql(database) for dimension in DIMENSIONS)
    statements.extend(fact.create_sql(database) for fact in FACTS)
    statements.append(QUARANTINE.create_sql(database))
    return statements


def table_names() -> list[str]:
    return (
        [dimension.name for dimension in DIMENSIONS]
        + [fact.name for fact in FACTS]
        + [QUARANTINE.name]
    )
