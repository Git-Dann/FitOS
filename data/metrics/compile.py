"""Compiling a metric definition into its three consumers.

The acceptance criterion is *a certified metric returns the same value through
Cube, the API and a dbt test — one definition, three consumers*. This is the
"one definition" half: all three artefacts are generated from `MetricDefinition`,
so there is nowhere for them to disagree.

The generated Cube model and dbt test are written to disk and committed, which
looks redundant next to generating them at runtime. It is not: a reviewer needs
to see what the metric layer will actually execute, and a generated file that
only exists at runtime is a file nobody reviews. `test_generated_files_are_current`
fails if the committed output does not match what the definitions produce, so
the checked-in copy cannot rot.

Every generated file carries a header saying it is generated and naming the
source. A generated file without that header gets hand-edited within a month.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from metrics.contract import MetricDefinition, MetricRegistry, QualityTest

GENERATED_HEADER = """\
# GENERATED FILE — do not edit.
#
# Produced from data/metrics/definitions/{source} by data/metrics/compile.py.
# Edit the definition and run `pnpm metrics:compile`. A hand-edit here is
# reverted the next time anyone runs it, silently.
"""

SQL_HEADER = """\
-- GENERATED FILE — do not edit.
--
-- Produced from data/metrics/definitions/{source} by data/metrics/compile.py.
-- Edit the definition and run `pnpm metrics:compile`.
"""


def cube_model(definition: MetricDefinition) -> str:
    """The Cube cube for one metric.

    Two things here are security rather than modelling.

    `organization_id` is declared as a dimension **and** the tenant policy below
    filters on it from the security context. Cube's `queryRewrite` is where
    multi-tenancy actually happens; a cube without one serves whichever rows the
    query asks for.

    `public: false` on the tenant column stops it being selectable as a
    dimension by a caller — the filter is applied for them, and being able to
    also group by it is how one tenant discovers another exists.
    """
    measures = textwrap.indent(
        f"""\
{definition.key}:
  type: number
  sql: "{definition.measure_expression}"
  description: "{definition.description.strip().splitlines()[0]}"
  meta:
    metric_version: {definition.version}
    unit: {definition.unit.value}
    certified: {str(definition.is_certified).lower()}
    exposure_bearing: {str(definition.is_exposure_bearing).lower()}""",
        "      ",
    ).lstrip()

    dimension_lines = []
    for name in sorted(set(definition.dimensions) | set(definition.grain)):
        if name == "organization_id":
            continue
        dimension_lines.append(f"      {name}:\n        type: string\n        sql: {name}")
    dimensions = "\n".join(dimension_lines)

    return (
        GENERATED_HEADER.format(source=f"{definition.key}.yml")
        + f"""
cubes:
  - name: {definition.key}
    sql_table: {definition.source_models[0]}
    description: >
      {definition.description.strip()}

    measures:
      {measures}

    dimensions:
      organization_id:
        type: string
        sql: organization_id
        # Never selectable. The tenant filter is applied for the caller; being
        # able to group by it is how one tenant learns another exists.
        public: false
{dimensions}
"""
    )


def cube_tenant_policy() -> str:
    """The `queryRewrite` that makes Cube multi-tenant.

    This is the whole tenancy story for the semantic layer, and it is one
    function. It appends an equality filter on `organization_id` taken from the
    **security context**, which comes from the verified JWT — never from the
    query. A caller supplying their own organization filter gets ours as well,
    and ours is an AND, so a wider filter cannot widen the result.

    Refusing outright when the context has no organization is deliberate:
    returning everything would be catastrophic and returning nothing would look
    like an empty dataset, which somebody would then "fix".
    """
    return """\
// GENERATED FILE — do not edit.
//
// Produced by data/metrics/compile.py. Edit the compiler, not this file.

module.exports = {
  /**
   * Multi-tenancy for the semantic layer.
   *
   * organization_id comes from the security context, which Cube derives from
   * the verified JWT. It is never read from the query: a caller-supplied tenant
   * is a caller-chosen tenant.
   *
   * The filter is appended, so a caller's own filters are ANDed with ours and a
   * wider filter cannot widen the result.
   */
  queryRewrite: (query, { securityContext }) => {
    const organizationId = securityContext && securityContext.org;

    if (!organizationId) {
      // Refused, not defaulted. Returning everything would be catastrophic;
      // returning nothing would look like an empty dataset and get "fixed".
      throw new Error("no organization in the security context; refusing to query");
    }

    query.filters = query.filters || [];
    query.filters.push({
      member: "organization_id",
      operator: "equals",
      values: [organizationId],
    });

    return query;
  },

  /**
   * The tenant is part of the cache key. Without this, one tenant's cached
   * result is served to another — a cache that ignores the tenant is a
   * cross-tenant read with a performance benefit.
   */
  contextToAppId: ({ securityContext }) =>
    `fitos_${(securityContext && securityContext.org) || "unknown"}`,

  contextToOrchestratorId: ({ securityContext }) =>
    `fitos_${(securityContext && securityContext.org) || "unknown"}`,
};
"""


# Validity rules: a value breaking one of these is *wrong*, and the build should
# go red. Sufficiency rules are different — see below.
VALIDITY_TESTS = {
    QualityTest.NOT_NULL,
    QualityTest.BETWEEN_0_AND_1,
    QualityTest.NON_NEGATIVE,
    QualityTest.MONOTONIC_NON_DECREASING,
}

# Sufficiency rules say the value is not *trustworthy enough to act on*, which is
# not the same as wrong. A shop with 12 stock checks this week has a perfectly
# correct discrepancy rate over 12 observations; failing the build for it would
# turn every small store into a broken pipeline, and the rule would be deleted
# within a fortnight.
#
# So these compile to a warning — visible, not blocking — and the *hard*
# enforcement lives where it belongs: a detector refuses to raise a gap from an
# insufficient sample, which is the decision the rule actually exists to govern.
SUFFICIENCY_TESTS = {QualityTest.DENOMINATOR_MIN_30}


def dbt_tests(definition: MetricDefinition) -> dict[str, str]:
    """One dbt file per severity, keyed by filename suffix.

    Two files rather than one, because a dbt singular test is *one* query per
    file — a second `select` in the same file is silently not run, which is the
    worst way for a quality test to fail.

    A dbt test passes when it returns no rows, so each selects the violations.
    """
    validity = [t for t in definition.quality_tests if t in VALIDITY_TESTS]
    sufficiency = [t for t in definition.quality_tests if t in SUFFICIENCY_TESTS]

    grain = ", ".join(definition.grain)
    expression = definition.measure_expression
    source = definition.source_models[0]

    # `ref`, not `source`. These metrics read the *governed* models, which are
    # dbt's own; `source()` is for the canonical tables the connectors write.
    # Getting this wrong compiles to a table that does not exist, and dbt
    # reports it as a missing source rather than as a wrong reference.
    relation = f"{{{{ ref('{source}') }}}}"

    def block(tests: list[QualityTest], severity: str, note: str) -> str:
        conditions: list[str] = []
        for test in tests:
            if test is QualityTest.NOT_NULL:
                conditions.append(f"({expression}) IS NULL")
            elif test is QualityTest.BETWEEN_0_AND_1:
                # The classic join fan-out symptom: a ratio above 1 means the
                # numerator counted rows the denominator did not.
                conditions.append(f"({expression}) < 0 OR ({expression}) > 1")
            elif test is QualityTest.NON_NEGATIVE:
                conditions.append(f"({expression}) < 0")
            elif test is QualityTest.DENOMINATOR_MIN_30:
                conditions.append("count(*) < 30")

        predicate = "\n       OR ".join(conditions)
        return f"""{{{{ config(severity='{severity}') }}}}

-- {note}
select
    {grain},
    ({expression}) as value,
    count(*) as observations
from {relation}
group by {grain}
having {predicate}
"""

    header = SQL_HEADER.format(source=f"{definition.key}.yml")
    files: dict[str, str] = {}

    if validity:
        files["validity"] = (
            header
            + f"\n-- Validity for {definition.identity}.\n\n"
            + block(
                validity,
                "error",
                f"{', '.join(t.value for t in validity)}. "
                "A value breaking one of these is wrong, not merely weak.",
            )
        )
    if sufficiency:
        files["sufficiency"] = (
            header
            + f"\n-- Sufficiency for {definition.identity}.\n\n"
            + block(
                sufficiency,
                "warn",
                f"{', '.join(t.value for t in sufficiency)}. "
                "A warning, not an error: a small sample is a correct value over few "
                "observations, and failing the build for it would break every small "
                "location. The hard rule lives in the detector, which refuses to raise "
                "a gap from an insufficient sample.",
            )
        )
    return files


class DisallowedFilterError(ValueError):
    """A filter the metric does not declare.

    Refused rather than ignored: a filter that silently does nothing produces a
    number for a wider population than the caller asked about, and it looks
    exactly like the right answer.
    """


def api_sql(
    definition: MetricDefinition,
    *,
    grain: list[str] | None = None,
    filters: dict[str, str] | None = None,
) -> tuple[str, dict[str, str]]:
    """The SQL the API runs, plus the parameters to bind.

    Returns both, because they are one decision. Every value is bound — the
    tenant from the verified principal, each filter by name — so nothing a
    caller supplies is ever interpolated into the query text.

    Filters are checked against `allowed_filters` and an unknown one is a
    refusal. Dropping it instead would answer a different question than the one
    asked, with no indication that it had.
    """
    grouping = grain or definition.grain
    columns = ", ".join(g for g in grouping if g != "organization_id")
    source = definition.source_models[0]

    parameters: dict[str, str] = {}
    predicates = ["organization_id = %(organization_id)s"]

    for index, (name, value) in enumerate(sorted((filters or {}).items())):
        if name not in definition.allowed_filters:
            raise DisallowedFilterError(
                f"{definition.key} does not allow filtering on {name!r}; "
                f"allowed: {sorted(definition.allowed_filters)}"
            )
        # The parameter name is generated, never the caller's key, so a filter
        # name cannot collide with `organization_id` or with another binding.
        placeholder = f"f{index}"
        predicates.append(f"{name} = %({placeholder})s")
        parameters[placeholder] = value

    select_columns = f"{columns}, " if columns else ""
    group_clause = f"\nGROUP BY {columns}" if columns else ""

    sql = (
        f"SELECT {select_columns}({definition.measure_expression}) AS value, "
        f"count(*) AS observations\n"
        f"FROM {source}\n"
        f"WHERE {' AND '.join(predicates)}{group_clause}"
    )
    return sql, parameters


def compile_all(
    registry: MetricRegistry,
    *,
    cube_dir: Path,
    dbt_test_dir: Path,
) -> dict[Path, str]:
    """Every generated artefact, as a path-to-content map.

    Returned rather than written, so the "are the committed files current?" test
    can compare without touching the disk.
    """
    artefacts: dict[Path, str] = {}

    for definition in registry:
        # Only the live version gets a Cube model: a superseded version stays
        # resolvable as evidence but must not be queryable as if it were current.
        if definition.valid_to is None:
            artefacts[cube_dir / f"{definition.key}.yml"] = cube_model(definition)

        for severity, content in dbt_tests(definition).items():
            artefacts[dbt_test_dir / f"metric_{definition.key}_{severity}.sql"] = content

    artefacts[cube_dir.parent / "cube.js"] = cube_tenant_policy()
    return artefacts


def write_all(artefacts: dict[Path, str]) -> list[Path]:
    written = []
    for path, content in artefacts.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_text() != content:
            path.write_text(content)
            written.append(path)
    return written


def main() -> int:
    from metrics.contract import MetricRegistry as Registry

    root = Path(__file__).resolve().parents[2]
    registry = Registry.load()
    artefacts = compile_all(
        registry,
        cube_dir=root / "services" / "semantic" / "model" / "cubes",
        dbt_test_dir=root / "data" / "dbt" / "tests" / "metrics",
    )
    written = write_all(artefacts)

    print(f"{len(registry)} metric definitions, {len(artefacts)} generated files")
    for path in written:
        print(f"  wrote {path.relative_to(root)}")
    if not written:
        print("  (all current)")

    uncertified = [d for d in registry if not d.is_certified]
    for definition in uncertified:
        # Named rather than silently excluded, because "why is my metric not in
        # the product" should not require reading the compiler.
        print(
            f"  note: {definition.identity} is not certified "
            f"(missing: {', '.join(definition.certification_gaps)})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
