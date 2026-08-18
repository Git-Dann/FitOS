"""The governed dbt models, against seeded data.

`dbt build` passing on empty tables proves the SQL parses. It does not prove the
models compute the right thing, and the Stock Truth model in particular has a
join whose correctness is the entire point of it: comparing a count against a
snapshot taken *after* the count would raise a gap against the person who did
the work.

So these seed data designed to be wrong under the plausible mistake, then assert
the model gets it right. The module runs `dbt build` itself, which also proves
the project compiles and deploys rather than assuming somebody ran it.
"""

from __future__ import annotations

import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

CLICKHOUSE_URL = os.environ.get("FITOS_CLICKHOUSE_URL", "http://127.0.0.1:8123/")
CLICKHOUSE_USER = os.environ.get("FITOS_CLICKHOUSE_USER", "fitos")
CLICKHOUSE_PASSWORD = os.environ.get("FITOS_CLICKHOUSE_PASSWORD", "fitos_local_only")
REQUIRE = bool(os.environ.get("FITOS_REQUIRE_CLICKHOUSE"))

DBT_DIR = Path(__file__).resolve().parents[2] / "dbt"


def _query(sql: str, database: str = "fitos") -> str:
    params = urllib.parse.urlencode(
        {"user": CLICKHOUSE_USER, "password": CLICKHOUSE_PASSWORD, "database": database}
    )
    request = urllib.request.Request(f"{CLICKHOUSE_URL}?{params}", data=sql.encode())
    with urllib.request.urlopen(request, timeout=60) as response:
        return str(response.read().decode())


def _available() -> bool:
    try:
        _query("SELECT 1", database="default")
    except (urllib.error.URLError, OSError):
        return False
    return True


def _dbt_available() -> bool:
    import shutil

    return shutil.which("dbt") is not None or (DBT_DIR / "dbt_project.yml").exists()


pytestmark = pytest.mark.skipif(
    not (_available() and _dbt_available()) and not REQUIRE,
    reason="ClickHouse or dbt is unavailable; set FITOS_REQUIRE_CLICKHOUSE=1 to require them",
)

ORG = uuid.uuid4()
CONNECTION = uuid.uuid4()


def _insert_snapshot(at: str, quantity: int) -> None:
    _query(
        "INSERT INTO fitos.fact_inventory_snapshot (organization_id, source_key, "
        "source_connection_id, source_record_id, lineage_ref, mapping_version, occurred_at, "
        "ingested_at, received_at, data_quality_flags, location_id, product_variant_id, "
        f"system_quantity) VALUES ('{ORG}', 'pos', '{CONNECTION}', 'SNAP-{at}', 'raw/s', 1, "
        f"'{at}', '2026-05-01 12:00:00.000', NULL, [], 'NS-014', 'SKU-1', {quantity})"
    )


def _insert_check(check_id: str, at: str, observed: int, variant: str = "SKU-1") -> None:
    _query(
        "INSERT INTO fitos.fact_stock_check (organization_id, source_key, "
        "source_connection_id, source_record_id, lineage_ref, mapping_version, occurred_at, "
        "ingested_at, received_at, data_quality_flags, check_id, location_id, "
        f"product_variant_id, staff_member_id, observed_quantity) VALUES ('{ORG}', "
        f"'csv_upload', '{CONNECTION}', '{check_id}', 'raw/c', 1, '{at}', "
        f"'2026-05-01 12:00:00.000', NULL, [], '{check_id}', 'NS-014', '{variant}', NULL, "
        f"{observed})"
    )


@pytest.fixture(scope="module", autouse=True)
def seeded_and_built() -> Iterator[None]:
    """Seed the trap, then build the models over it."""
    if not _available():
        pytest.fail("FITOS_REQUIRE_CLICKHOUSE is set but ClickHouse is not reachable")

    from canonical.schema import all_statements

    for statement in all_statements():
        _query(statement, database="default")

    # Three snapshots around one count at 10:00. The 09:30 reading is the only
    # correct comparison: 08:00 is stale, and 11:00 had not happened yet when
    # the person did the count.
    _insert_snapshot("2026-05-01 08:00:00.000", 50)
    _insert_snapshot("2026-05-01 09:30:00.000", 42)
    _insert_snapshot("2026-05-01 11:00:00.000", 7)
    _insert_check("CHK-1", "2026-05-01 10:00:00.000", observed=35)

    # A variant the inventory feed has never covered.
    _insert_check("CHK-2", "2026-05-01 10:05:00.000", observed=3, variant="SKU-NEVER-SEEN")

    result = subprocess.run(
        ["uv", "run", "dbt", "build", "--no-use-colors"],  # noqa: S607
        cwd=DBT_DIR,
        env={**os.environ, "DBT_PROFILES_DIR": str(DBT_DIR)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"dbt build failed:\n{result.stdout[-4000:]}"

    yield

    _query(f"ALTER TABLE fitos.fact_stock_check DELETE WHERE organization_id = '{ORG}'")
    _query(f"ALTER TABLE fitos.fact_inventory_snapshot DELETE WHERE organization_id = '{ORG}'")


def test_dbt_build_succeeds() -> None:
    """The fixture asserts it; this names it so a failure reads correctly."""
    assert (DBT_DIR / "dbt_project.yml").exists()


def test_the_stock_check_compares_against_the_snapshot_before_it(
    seeded_and_built: None,
) -> None:
    """RELEASE-BLOCKING for the Stock Truth Gap.

    Three snapshots exist: 50 at 08:00, 42 at 09:30 and 7 at 11:00. The count of
    35 happened at 10:00.

    The only correct comparison is 42. Picking 7 — the nearest snapshot in
    absolute time — would report a discrepancy of -28 and raise a gap against
    somebody who counted correctly, because at 10:00 that snapshot had not
    happened yet.
    """
    row = _query(
        "SELECT toString(snapshot_at), toString(system_quantity), toString(discrepancy) "
        "FROM fitos_governed.gov_stock_truth "
        f"WHERE organization_id = '{ORG}' AND check_id = 'CHK-1'"
    ).strip()

    snapshot_at, system_quantity, discrepancy = row.split("\t")
    assert snapshot_at.startswith("2026-05-01 09:30"), (
        f"compared against the wrong snapshot: {snapshot_at}"
    )
    assert system_quantity == "42"
    assert discrepancy == "7"


def test_the_discrepancy_rate_is_a_proportion_of_what_the_system_believed(
    seeded_and_built: None,
) -> None:
    rate = _query(
        "SELECT round(discrepancy_rate, 4) FROM fitos_governed.gov_stock_truth "
        f"WHERE organization_id = '{ORG}' AND check_id = 'CHK-1'"
    ).strip()
    assert rate == "0.1666", rate


def test_a_variant_with_no_snapshot_is_kept_with_a_null_rate(
    seeded_and_built: None,
) -> None:
    """A variant the inventory feed has never covered is a finding, not a gap.

    An inner join would delete the evidence of it, and a rate of zero would
    read as "no discrepancy" — which is the most misleading possible answer,
    because it says the thing we know nothing about is fine.
    """
    row = _query(
        "SELECT isNull(snapshot_at), isNull(discrepancy_rate) "
        "FROM fitos_governed.gov_stock_truth "
        f"WHERE organization_id = '{ORG}' AND check_id = 'CHK-2'"
    ).strip()
    assert row == "1\t1", row


def test_no_governed_model_hard_codes_a_tenant(seeded_and_built: None) -> None:
    """The query layer injects the tenant; a model that filtered would be wrong.

    A hard-coded organization would serve the wrong tenant the first time the
    model was reused, and would look correct until then.

    The check is for a UUID *literal*, not for the string "organization_id =" —
    joining two CTEs on the tenant column is exactly right and an earlier
    version of this test flagged it, which would have taught everyone to ignore
    the test.
    """
    import re

    uuid_literal = re.compile(r"'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-", re.ASCII)
    for model in ("gov_transactions", "gov_stock_truth", "gov_data_quality"):
        sql = (DBT_DIR / "models" / "governed" / f"{model}.sql").read_text()
        assert not uuid_literal.search(sql), f"{model} contains a hard-coded identifier"


def test_every_governed_model_selects_the_tenant_column(seeded_and_built: None) -> None:
    """Otherwise the query layer has nothing to inject a predicate against."""
    for model in ("gov_transactions", "gov_stock_truth", "gov_data_quality"):
        columns = _query(
            "SELECT name FROM system.columns "
            f"WHERE database = 'fitos_governed' AND table = '{model}'"
        ).split()
        assert "organization_id" in columns, model
