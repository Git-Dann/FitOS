"""Retail detector rules.

Each function returns a configured rule, not a detector class. The classes are
generic and live in `fitos_worker.detectors`; this module supplies the
vocabulary — gap type, copy, canonical entity, playbook — that makes one of them
a retail finding.

`rule_id` is passed in rather than generated, because it is a stable identity
that lands on every gap as part of the reproducibility triple. A rule that
generated its own id each time would make every gap look like it came from a
different rule.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fitos_worker.detectors.source_mismatch import SourceMismatchConfig

PACK_KEY = "retail_omnichannel"


def stock_truth_rule(
    *,
    rule_id: UUID,
    version: int = 1,
    threshold_rate: Decimal = Decimal("0.05"),
    expected_rate: Decimal = Decimal("0.02"),
) -> SourceMismatchConfig:
    """The Stock Truth Gap: the inventory record and the count disagree.

    The copy states the disagreement and nothing else. It does not say
    shrinkage, miscount or theft — the metric establishes that two sources
    differ, and every one of those words is a cause it has not established.
    """
    return SourceMismatchConfig(
        rule_id=rule_id,
        version=version,
        pack_key=PACK_KEY,
        gap_type="stock_truth_mismatch",
        canonical_entity="fact_stock_count",
        scope_dimension="location_id",
        expected_rate=expected_rate,
        threshold_rate=threshold_rate,
        title_template="Stock records and counts disagree at {scope_id} ({rate} of checks)",
        summary_template=(
            "{rate} of {observations} stock checks in this window found a quantity "
            "different from the inventory record. The two sources disagree; which one "
            "is right is not established by this metric."
        ),
        action_key="recount_location",
        action_title="Recount the affected variants",
        action_rationale=(
            "Confirms whether the disagreement is in the count or in the inventory "
            "record before anything is adjusted."
        ),
        action_playbook_id="retail.stock_truth.recount",
    )
