"""Fulfilment routing, including the five cases ported from the prototype.

The five tests under "Ported behavioural cases" are the ones
`legacy/fitos-prototype/tests/fulfilment.test.ts` covered, asserting the same
outcomes against the new module. They are ported rather than reimplemented: the
prototype's behaviour is a product requirement (docs/product-spec.md §7), so a
change in what they assert is a change in the product, not a refactor.

`test_accessibility_restores_staff_delivery_at_red` is the golden test §7.4
names. It is marked because it is the one case here that must never be
weakened: somebody with an accessibility need loses the route they depend on
if it goes.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pytest
from fitos_api.fulfilment.policy import (
    DEFAULT_METHODS,
    Capacity,
    FulfilmentRequest,
    Location,
    Method,
    RetailerPolicy,
    StockConfidence,
    TimingPreference,
    UnmetReason,
    capacity_from_queue,
    rank_fulfilment,
    stock_is_usable,
)


def request(**overrides: object) -> FulfilmentRequest:
    """The prototype's fixture, field for field."""
    base: dict[str, object] = {
        "capacity": Capacity.GREEN,
        "active_associates": 4,
        "queue_length": 2,
        "companion_present": False,
        "location": Location.SHOP_FLOOR,
        "stock_confidence": StockConfidence.CONFIRMED,
        "stock_units": 6,
        "walking_minutes": 2,
        "timing_preference": TimingPreference.AS_SOON_AS_POSSIBLE,
        "accessibility_need": False,
        "batch_opportunity": False,
        "online_available": True,
        "nearby_store_available": True,
    }
    base.update(overrides)
    return FulfilmentRequest(**base)  # type: ignore[arg-type]


def methods(options: list) -> list[Method]:  # type: ignore[type-arg]
    return [o.method for o in options]


# ---------------------------------------------------------------------------
# Ported behavioural cases
# ---------------------------------------------------------------------------


def test_green_capacity_favours_immediate_staff_delivery_for_confirmed_floor_stock() -> None:
    results = rank_fulfilment(request())
    assert results[0].method is Method.STAFF_DELIVERY_NOW
    assert "confirmed item" in results[0].explanation


def test_amber_capacity_promotes_companion_collection_and_batch_opportunities() -> None:
    companion = rank_fulfilment(
        request(
            capacity=Capacity.AMBER,
            companion_present=True,
            location=Location.STOCKROOM,
            walking_minutes=4,
            batch_opportunity=True,
        )
    )
    assert companion[0].method is Method.COMPANION_COLLECTION

    batch = rank_fulfilment(
        request(
            capacity=Capacity.AMBER,
            companion_present=False,
            location=Location.STOCKROOM,
            walking_minutes=4,
            batch_opportunity=True,
        )
    )
    assert batch[0].method is Method.BATCH_PICK


def test_red_capacity_limits_immediate_delivery() -> None:
    restricted = rank_fulfilment(request(capacity=Capacity.RED))
    assert restricted[0].method is not Method.STAFF_DELIVERY_NOW
    assert Method.STAFF_DELIVERY_NOW not in methods(restricted)


def test_accessibility_restores_staff_delivery_at_red() -> None:
    """GOLDEN TEST — docs/product-spec.md §7.4, non-negotiable.

    An accessibility need restores staff delivery at Red. If this test is ever
    weakened, somebody loses the only route they can use.
    """
    protected = rank_fulfilment(request(capacity=Capacity.RED, accessibility_need=True))
    assert protected[0].method is Method.STAFF_DELIVERY_NOW
    assert "accessibility need" in protected[0].explanation
    assert "accessibility_need" in protected[0].reason_codes


def test_uncertain_or_unavailable_stock_promotes_alternative_and_external_options() -> None:
    results = rank_fulfilment(request(stock_confidence=StockConfidence.CHECK, stock_units=2))
    assert results[0].method is Method.ALTERNATIVE_PRODUCT
    assert Method.RESERVE_NEARBY in methods(results)
    assert Method.HOME_DELIVERY in methods(results)


def test_retailer_policy_can_disable_a_method_and_raise_the_confidence_threshold() -> None:
    policy = RetailerPolicy(
        enabled_methods=tuple(m for m in DEFAULT_METHODS if m is not Method.STAFF_DELIVERY_NOW),
        minimum_stock_confidence=StockConfidence.CONFIRMED,
    )
    results = rank_fulfilment(request(stock_confidence=StockConfidence.LIKELY), policy)
    assert Method.STAFF_DELIVERY_NOW not in methods(results)
    assert results[0].method is Method.ALTERNATIVE_PRODUCT


# ---------------------------------------------------------------------------
# The accessibility override cannot be outvoted
# ---------------------------------------------------------------------------


def test_the_override_is_an_availability_rule_not_a_ranking_one() -> None:
    """§7.4 says an accessibility need *restores* staff delivery at Red.

    It does not say the route must rank first, and the prototype does not make
    it rank first either: at Red with a companion present, companion collection
    scores 91 against the restored route's 82. That is shipped behaviour and a
    companion collecting is not a worse outcome, so it is preserved rather than
    quietly changed — see docs/build-state.md, where it is recorded as a
    question for the product owner.
    """
    protected = rank_fulfilment(
        request(capacity=Capacity.RED, accessibility_need=True, companion_present=True)
    )
    assert Method.STAFF_DELIVERY_NOW in methods(protected), "the route must be available"
    assert protected[0].method is Method.COMPANION_COLLECTION


def test_the_override_does_not_re_rank_above_red() -> None:
    """At Amber the route was never withheld, so there is nothing to restore.

    The prototype ranks a batched pick above staff delivery here even with an
    accessibility need. Applying the override at Amber would silently change
    that for 456 of the 3,888 cases in the differential grid — which is how the
    divergence was found.
    """
    amber = rank_fulfilment(
        request(capacity=Capacity.AMBER, accessibility_need=True, batch_opportunity=True)
    )
    assert amber[0].method is Method.BATCH_PICK
    assert Method.STAFF_DELIVERY_NOW in methods(amber)


def test_the_override_survives_the_availability_expression_being_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reason the rule is applied last rather than inlined.

    Simulating the edit the structure exists to survive: the availability clause
    stops allowing staff delivery at Red. The override notices the route is
    missing and restores it, so the rule fails visibly rather than silently.
    """
    from fitos_api.fulfilment import policy as module

    original = module._offer_stocked_routes

    def without_the_clause(req, pol, offer, direct_minutes):  # type: ignore[no-untyped-def]
        stripped = req.model_copy(update={"accessibility_need": False})
        original(stripped, pol, offer, direct_minutes)

    monkeypatch.setattr(module, "_offer_stocked_routes", without_the_clause)

    protected = module.rank_fulfilment(request(capacity=Capacity.RED, accessibility_need=True))
    assert Method.STAFF_DELIVERY_NOW in methods(protected)
    restored = next(o for o in protected if o.method is Method.STAFF_DELIVERY_NOW)
    assert "accessibility need" in restored.explanation


def test_the_override_does_not_apply_without_an_accessibility_need() -> None:
    """A rule that always fires is not a rule, it is a default."""
    ordinary = rank_fulfilment(request(capacity=Capacity.RED, companion_present=True))
    assert Method.STAFF_DELIVERY_NOW not in methods(ordinary)


def test_the_override_cannot_conjure_a_disabled_method() -> None:
    """A retailer that disabled the method entirely made a policy decision the
    override does not overrule — it cannot offer a route that does not exist."""
    policy = RetailerPolicy(
        enabled_methods=tuple(m for m in DEFAULT_METHODS if m is not Method.STAFF_DELIVERY_NOW)
    )
    results = rank_fulfilment(request(capacity=Capacity.RED, accessibility_need=True), policy)
    assert Method.STAFF_DELIVERY_NOW not in methods(results)
    assert results, "the request still has to produce a record"


def test_the_override_does_not_promise_stock_that_is_not_there() -> None:
    """Restoring a delivery route for stock the retailer does not believe it has
    would turn an accessibility protection into a broken promise."""
    results = rank_fulfilment(
        request(capacity=Capacity.RED, accessibility_need=True, stock_units=0)
    )
    assert Method.STAFF_DELIVERY_NOW not in methods(results)


def test_the_override_is_a_reorder_not_a_duplicate() -> None:
    protected = rank_fulfilment(request(capacity=Capacity.RED, accessibility_need=True))
    assert methods(protected).count(Method.STAFF_DELIVERY_NOW) == 1


# ---------------------------------------------------------------------------
# Stock confidence is ordinal (§7.1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("minimum", "actual", "usable"),
    [
        (StockConfidence.LIKELY, StockConfidence.CONFIRMED, True),
        (StockConfidence.LIKELY, StockConfidence.LIKELY, True),
        (StockConfidence.LIKELY, StockConfidence.CHECK, False),
        (StockConfidence.CONFIRMED, StockConfidence.LIKELY, False),
        (StockConfidence.CHECK, StockConfidence.CHECK, True),
    ],
)
def test_confidence_is_compared_by_rank_not_equality(
    minimum: StockConfidence, actual: StockConfidence, usable: bool
) -> None:
    policy = RetailerPolicy(minimum_stock_confidence=minimum)
    assert stock_is_usable(request(stock_confidence=actual), policy) is usable


def test_zero_units_is_unusable_at_any_confidence() -> None:
    """Confidence in a count of zero is still zero units. Both are required."""
    policy = RetailerPolicy(minimum_stock_confidence=StockConfidence.CHECK)
    assert not stock_is_usable(
        request(stock_units=0, stock_confidence=StockConfidence.CONFIRMED), policy
    )


# ---------------------------------------------------------------------------
# Capacity from queue (§7.3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("queue", "expected"),
    [
        (0, Capacity.GREEN),
        (4, Capacity.GREEN),
        (5, Capacity.AMBER),
        (9, Capacity.AMBER),
        (10, Capacity.RED),
        (99, Capacity.RED),
    ],
)
def test_capacity_steps_at_the_configured_thresholds(queue: int, expected: Capacity) -> None:
    assert capacity_from_queue(queue, RetailerPolicy()) is expected


def test_thresholds_are_tenant_configuration() -> None:
    tight = RetailerPolicy(queue_amber_threshold=2, queue_red_threshold=3)
    assert capacity_from_queue(2, tight) is Capacity.AMBER
    assert capacity_from_queue(3, tight) is Capacity.RED


def test_an_unreachable_amber_band_is_refused() -> None:
    """Amber above red means the red branch claims every queue that would have
    been amber, and the state silently never occurs."""
    with pytest.raises(ValueError, match="never be reached"):
        RetailerPolicy(queue_amber_threshold=10, queue_red_threshold=5)


# ---------------------------------------------------------------------------
# An unfulfillable request is a record, not a silence (§7.5)
# ---------------------------------------------------------------------------


def test_a_request_with_nothing_available_still_produces_a_record() -> None:
    results = rank_fulfilment(
        request(stock_units=0, online_available=False, nearby_store_available=False),
        RetailerPolicy(enabled_methods=()),
    )
    assert len(results) == 1
    assert results[0].method is Method.UNABLE_TO_FULFIL


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"stock_units": 0}, UnmetReason.NO_STOCK),
        ({"stock_confidence": StockConfidence.CHECK}, UnmetReason.CONFIDENCE_BELOW_MINIMUM),
    ],
)
def test_the_unmet_record_carries_a_machine_readable_reason(
    overrides: dict[str, object], expected: UnmetReason
) -> None:
    """ "Could not fulfil" and "could not fulfil because the count was too old to
    trust" are different facts, and only the second tells the stock-truth gap
    family anything."""
    results = rank_fulfilment(
        request(online_available=False, nearby_store_available=False, **overrides),
        RetailerPolicy(enabled_methods=(Method.ALTERNATIVE_PRODUCT,)),
    )
    assert expected.value in results[0].reason_codes


def test_a_fully_disabled_policy_names_the_configuration_as_the_reason() -> None:
    results = rank_fulfilment(request(), RetailerPolicy(enabled_methods=()))
    assert results[0].method is Method.UNABLE_TO_FULFIL
    assert UnmetReason.NO_ENABLED_METHOD.value in results[0].reason_codes


# ---------------------------------------------------------------------------
# Promises and determinism
# ---------------------------------------------------------------------------


def test_an_estimate_past_the_promise_window_refuses_to_promise() -> None:
    """Quoting "about 40 min" past a 12-minute maximum promise is a number the
    retailer has not agreed to stand behind."""
    slow = rank_fulfilment(request(walking_minutes=60))
    staff = next(o for o in slow if o.method is Method.STAFF_DELIVERY_NOW)
    assert staff.estimate == "Timing will be confirmed"


def test_an_estimate_inside_the_window_states_the_minutes() -> None:
    staff = next(o for o in rank_fulfilment(request()) if o.method is Method.STAFF_DELIVERY_NOW)
    assert staff.estimate == "About 3 min"


def test_ranking_is_deterministic() -> None:
    """A golden test over a non-deterministic function proves nothing."""
    first = rank_fulfilment(request(capacity=Capacity.AMBER, batch_opportunity=True))
    second = rank_fulfilment(request(capacity=Capacity.AMBER, batch_opportunity=True))
    assert first == second


def test_equal_scores_break_ties_by_method_not_insertion_order() -> None:
    """Otherwise the order options happen to be appended in leaks into the
    output and a golden fixture starts flapping on an unrelated edit."""
    options = rank_fulfilment(request())
    scores = [(o.score, o.method.value) for o in options]
    assert scores == sorted(scores, key=lambda pair: (-pair[0], pair[1]))


def test_the_policy_version_is_part_of_the_configuration() -> None:
    """A routing decision made in March stays explicable by the March policy."""
    assert RetailerPolicy().version == 1
    assert RetailerPolicy(version=4).version == 4
    with pytest.raises(ValueError, match="version"):
        RetailerPolicy(version=0)


def test_an_unknown_policy_key_is_refused() -> None:
    with pytest.raises(ValueError, match="batch_window_minuets"):
        RetailerPolicy(batch_window_minuets=8)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Differential parity with the prototype
# ---------------------------------------------------------------------------


# Recorded by running the prototype's own engine over the grid; gzipped because
# 3,888 cases is 1.9 MB of JSON and a fixture nobody wants in a diff is a
# fixture that gets deleted.
LEGACY_GRID = Path(__file__).parent / "fixtures" / "legacy_fulfilment_grid.json.gz"


def _load_grid() -> list[dict[str, Any]]:
    with gzip.open(LEGACY_GRID, "rt") as handle:
        return list(json.load(handle))


_CAPACITY = {"Green": Capacity.GREEN, "Amber": Capacity.AMBER, "Red": Capacity.RED}
_CONFIDENCE = {
    "Confirmed": StockConfidence.CONFIRMED,
    "Likely": StockConfidence.LIKELY,
    "Check": StockConfidence.CHECK,
}
_LOCATION = {"Shop floor": Location.SHOP_FLOOR, "Stockroom": Location.STOCKROOM}
_TIMING = {
    "As soon as possible": TimingPreference.AS_SOON_AS_POSSIBLE,
    "Before I finish": TimingPreference.BEFORE_I_FINISH,
    "No rush": TimingPreference.NO_RUSH,
}
# The prototype's display strings, which are what the recorded grid contains.
_LEGACY_NAME = {
    Method.STAFF_DELIVERY_NOW: "Staff delivery now",
    Method.COMPANION_COLLECTION: "Companion collection",
    Method.CUSTOMER_SELF_COLLECTION: "Customer self-collection",
    Method.BATCH_PICK: "Batch pick",
    Method.BRING_BEFORE_I_FINISH: "Bring before I finish",
    Method.COLLECT_AT_CHECKOUT: "Collect at checkout",
    Method.RESERVE_NEARBY: "Reserve nearby",
    Method.HOME_DELIVERY: "Home delivery",
    Method.ALTERNATIVE_PRODUCT: "Alternative product",
    Method.UNABLE_TO_FULFIL: "Unable to fulfil",
}


def _from_grid(recorded: dict[str, Any]) -> FulfilmentRequest:
    return FulfilmentRequest(
        capacity=_CAPACITY[recorded["capacity"]],
        active_associates=4,
        queue_length=2,
        companion_present=recorded["companionPresent"],
        location=_LOCATION[recorded["location"]],
        stock_confidence=_CONFIDENCE[recorded["stockConfidence"]],
        stock_units=recorded["stockUnits"],
        walking_minutes=recorded["walkingMinutes"],
        timing_preference=_TIMING[recorded["timingPreference"]],
        accessibility_need=recorded["accessibilityNeed"],
        batch_opportunity=recorded["batchOpportunity"],
        online_available=True,
        nearby_store_available=True,
    )


def test_the_grid_covers_every_combination_it_claims_to() -> None:
    """A parity fixture that shrank would still pass the comparison below."""
    cases = _load_grid()
    assert len(cases) == 3888
    assert len({c["input"]["capacity"] for c in cases}) == 3
    assert len({c["input"]["stockConfidence"] for c in cases}) == 3


def test_routing_matches_the_prototype_on_every_recorded_case() -> None:
    """The port preserved semantics, proved rather than asserted.

    3,888 combinations recorded from `legacy/fitos-prototype` by running its own
    engine, compared method-for-method, score-for-score and estimate-for-
    estimate. Five hand-written cases pass against a port that has quietly
    changed behaviour everywhere they do not look — this found exactly that: an
    accessibility override applied at every capacity instead of only at Red
    diverged on 456 of these cases while all five ported tests still passed.
    """
    cases = _load_grid()
    divergent: list[str] = []

    for case in cases:
        options = rank_fulfilment(_from_grid(case["input"]), RetailerPolicy())
        ours = [_LEGACY_NAME[o.method] for o in options]
        if (
            ours != case["methods"]
            or [o.score for o in options] != case["scores"]
            or [o.estimate for o in options] != case["estimates"]
        ):
            divergent.append(f"{case['input']}\n  legacy: {case['methods']}\n  ours  : {ours}")

    assert not divergent, (
        f"{len(divergent)} of {len(cases)} cases diverge from the prototype:\n"
        + "\n".join(divergent[:5])
    )
