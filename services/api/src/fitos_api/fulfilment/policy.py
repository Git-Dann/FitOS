"""Fulfilment routing.

Carried forward from `legacy/fitos-prototype/app/ui/fulfilment-engine.ts`, whose
behaviour is a product requirement rather than a migration note
(docs/product-spec.md §7). The five cases its tests covered are ported verbatim
in `test_fulfilment.py`, the accessibility override included.

What changed in the move, and why each change is not cosmetic:

**Policy is versioned, tenant-scoped configuration.** The prototype had one
module-level default. A retailer disabling staff delivery or raising the minimum
stock confidence is now a policy version, so a routing decision made in March
stays explicable by the March policy. A recommendation nobody can reconstruct is
a recommendation nobody can argue with.

**Scores are named constants, not literals inside a ranking expression.** The
prototype scattered numbers like 98, 63 and 82 through one long function. They
were correct; they were also unreviewable, because you could not tell which of
them encoded a policy decision and which was reached by trial and error.

**The accessibility override restores availability, and is applied last.**
§7.4: "an accessibility need restores staff delivery at Red". It is an
availability rule, not a ranking rule — at Red the route is withheld, and an
accessibility need puts it back. It runs after the routes are assembled so a
future edit to the availability expression cannot drop it silently.

Two things the differential check against the prototype exposed, both preserved
because they are the shipped behaviour and changing them is a product decision
rather than a port:

  - At Amber, `batch_pick` scores 88 against staff delivery's 63, so a customer
    with an accessibility need is offered a batched pick first. The override
    does not apply at Amber, because the route was never withheld there.
  - At Red with a companion present, `companion_collection` scores 91 against
    the restored staff delivery's 82 and ranks above it. The prototype's golden
    test does not cover this because its fixture has no companion, so the
    guarantee it appears to assert is fixture-dependent.

Neither is obviously wrong — a companion collecting is not a worse outcome — but
neither is obviously right either, and both are recorded in docs/build-state.md
as questions for the product owner rather than decided here.

**An unfulfillable request produces a record, not a silence** (§7.5). The
prototype returned an `Unable to fulfil` option; that is kept, and it now
carries a machine-readable reason so unmet demand can feed the stock-availability
and stock-truth gap families rather than disappearing into a UI string.

**Stock confidence stays ordinal** (§7.1). `Confirmed > Likely > Check`, compared
by rank against a tenant minimum. Availability is a claim with a confidence,
never a fact, and a boolean would erase exactly that.

The customer-facing explanations are still here rather than in the pack, and
`test_pack_contract.py` keeps them free of pack vocabulary. They belong with the
rest of the product copy and should move to `packs/retail` when the UI copy
lands in Phase E; recorded in docs/build-state.md rather than left implicit.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Capacity(StrEnum):
    GREEN = "green"
    AMBER = "amber"
    RED = "red"


class StockConfidence(StrEnum):
    """Ordinal, not boolean. Availability is a claim with a confidence."""

    CHECK = "check"
    LIKELY = "likely"
    CONFIRMED = "confirmed"


CONFIDENCE_RANK: dict[StockConfidence, int] = {
    StockConfidence.CHECK: 1,
    StockConfidence.LIKELY: 2,
    StockConfidence.CONFIRMED: 3,
}


class Method(StrEnum):
    STAFF_DELIVERY_NOW = "staff_delivery_now"
    COMPANION_COLLECTION = "companion_collection"
    CUSTOMER_SELF_COLLECTION = "customer_self_collection"
    BATCH_PICK = "batch_pick"
    BRING_BEFORE_I_FINISH = "bring_before_i_finish"
    COLLECT_AT_CHECKOUT = "collect_at_checkout"
    RESERVE_NEARBY = "reserve_nearby"
    HOME_DELIVERY = "home_delivery"
    ALTERNATIVE_PRODUCT = "alternative_product"
    UNABLE_TO_FULFIL = "unable_to_fulfil"


class Location(StrEnum):
    SHOP_FLOOR = "shop_floor"
    STOCKROOM = "stockroom"


class TimingPreference(StrEnum):
    AS_SOON_AS_POSSIBLE = "as_soon_as_possible"
    BEFORE_I_FINISH = "before_i_finish"
    NO_RUSH = "no_rush"


class UnmetReason(StrEnum):
    """Why nothing could be offered. Machine-readable so unmet demand is a fact
    row feeding the stock gap families, not a sentence in a UI."""

    NO_STOCK = "no_stock"
    CONFIDENCE_BELOW_MINIMUM = "confidence_below_minimum"
    NO_ENABLED_METHOD = "no_enabled_method"


# Ranking weights. Named because a bare 98 next to a bare 82 in a ranking
# expression tells a reviewer nothing about which is a policy decision.
SCORE_STAFF_DELIVERY_GREEN = 98
SCORE_STAFF_DELIVERY_AMBER = 63
SCORE_STAFF_DELIVERY_ACCESSIBILITY = 82
SCORE_COMPANION_GREEN = 76
SCORE_COMPANION_CONSTRAINED = 91
SCORE_SELF_COLLECTION_RED = 74
SCORE_SELF_COLLECTION = 48
SCORE_BATCH_AMBER = 88
SCORE_BATCH = 70
SCORE_BEFORE_I_FINISH_PREFERRED = 86
SCORE_BEFORE_I_FINISH = 42
SCORE_CHECKOUT_PREFERRED = 75
SCORE_CHECKOUT = 45
SCORE_RESERVE_NEARBY_WITH_STOCK = 39
SCORE_RESERVE_NEARBY_WITHOUT_STOCK = 81
SCORE_HOME_DELIVERY_WITH_STOCK = 31
SCORE_HOME_DELIVERY_WITHOUT_STOCK = 77
SCORE_ALTERNATIVE_PRODUCT = 96
SCORE_UNABLE = 1

DEFAULT_METHODS: tuple[Method, ...] = (
    Method.STAFF_DELIVERY_NOW,
    Method.COMPANION_COLLECTION,
    Method.CUSTOMER_SELF_COLLECTION,
    Method.BATCH_PICK,
    Method.BRING_BEFORE_I_FINISH,
    Method.COLLECT_AT_CHECKOUT,
    Method.RESERVE_NEARBY,
    Method.HOME_DELIVERY,
    Method.ALTERNATIVE_PRODUCT,
)


class RetailerPolicy(BaseModel):
    """Tenant-scoped, versioned routing configuration.

    `version` lands on every routing decision. A retailer raising the minimum
    stock confidence changes what is offered from that point on and does not
    retroactively make yesterday's recommendation look wrong.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(default=1, ge=1)
    enabled_methods: tuple[Method, ...] = DEFAULT_METHODS
    queue_amber_threshold: int = Field(default=5, ge=0)
    queue_red_threshold: int = Field(default=10, ge=0)
    batch_window_minutes: int = Field(default=8, ge=0)
    maximum_promise_minutes: int = Field(default=12, ge=0)
    minimum_stock_confidence: StockConfidence = StockConfidence.LIKELY

    @model_validator(mode="after")
    def _thresholds_are_ordered(self) -> RetailerPolicy:
        if self.queue_amber_threshold > self.queue_red_threshold:
            # Amber above red is unreachable: the red branch would claim every
            # queue that would have been amber, and the amber state would
            # silently never occur.
            raise ValueError(
                f"amber threshold {self.queue_amber_threshold} is above red "
                f"{self.queue_red_threshold}; amber would never be reached"
            )
        return self

    def enables(self, method: Method) -> bool:
        return method in self.enabled_methods


class FulfilmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    capacity: Capacity
    active_associates: int = Field(default=0, ge=0)
    queue_length: int = Field(default=0, ge=0)
    companion_present: bool = False
    location: Location = Location.SHOP_FLOOR
    stock_confidence: StockConfidence = StockConfidence.CONFIRMED
    stock_units: int = Field(default=0, ge=0)
    walking_minutes: int = Field(default=0, ge=0)
    timing_preference: TimingPreference = TimingPreference.AS_SOON_AS_POSSIBLE
    accessibility_need: bool = False
    batch_opportunity: bool = False
    online_available: bool = True
    nearby_store_available: bool = True


class FulfilmentOption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method: Method
    score: int
    estimate: str
    explanation: str
    reason_codes: tuple[str, ...] = ()


def capacity_from_queue(queue_length: int, policy: RetailerPolicy) -> Capacity:
    if queue_length >= policy.queue_red_threshold:
        return Capacity.RED
    if queue_length >= policy.queue_amber_threshold:
        return Capacity.AMBER
    return Capacity.GREEN


def stock_is_usable(request: FulfilmentRequest, policy: RetailerPolicy) -> bool:
    """Units *and* confidence. Either alone is a claim the other contradicts."""
    if request.stock_units <= 0:
        return False
    return (
        CONFIDENCE_RANK[request.stock_confidence]
        >= CONFIDENCE_RANK[policy.minimum_stock_confidence]
    )


def unmet_reason(request: FulfilmentRequest, policy: RetailerPolicy) -> UnmetReason | None:
    """Why stock could not be used. None when it could.

    Separate from `stock_is_usable` so the *reason* survives into the unmet
    demand record. "Could not fulfil" and "could not fulfil because the count
    was too old to trust" are different facts, and only the second tells the
    stock-truth gap family anything.
    """
    if request.stock_units <= 0:
        return UnmetReason.NO_STOCK
    if CONFIDENCE_RANK[request.stock_confidence] < CONFIDENCE_RANK[policy.minimum_stock_confidence]:
        return UnmetReason.CONFIDENCE_BELOW_MINIMUM
    return None


def _estimate(minutes: int, policy: RetailerPolicy) -> str:
    """Beyond the promise window the answer is a refusal to promise.

    Quoting "about 40 min" past a 12-minute maximum promise is a number the
    retailer has not agreed to stand behind.
    """
    if minutes <= policy.maximum_promise_minutes:
        return f"About {minutes} min"
    return "Timing will be confirmed"


def rank_fulfilment(
    request: FulfilmentRequest, policy: RetailerPolicy | None = None
) -> list[FulfilmentOption]:
    """Rank the routes available for one request. Pure and deterministic.

    No clock, no I/O: the same request under the same policy always produces the
    same ordering, which is what makes the golden tests meaningful and what lets
    a routing decision be replayed months later from its policy version.
    """
    policy = policy or RetailerPolicy()
    options: list[FulfilmentOption] = []
    stock_ready = stock_is_usable(request, policy)
    direct_minutes = max(
        2, request.walking_minutes + (3 if request.location is Location.STOCKROOM else 1)
    )

    def offer(
        method: Method,
        score: int,
        minutes: int,
        explanation: str,
        *,
        available: bool = True,
        reason_codes: tuple[str, ...] = (),
    ) -> None:
        if policy.enables(method) and available:
            options.append(
                FulfilmentOption(
                    method=method,
                    score=score,
                    estimate=_estimate(minutes, policy),
                    explanation=explanation,
                    reason_codes=reason_codes,
                )
            )

    if stock_ready:
        _offer_stocked_routes(request, policy, offer, direct_minutes)

    if request.nearby_store_available:
        offer(
            Method.RESERVE_NEARBY,
            SCORE_RESERVE_NEARBY_WITH_STOCK if stock_ready else SCORE_RESERVE_NEARBY_WITHOUT_STOCK,
            0,
            "A nearby store has an option that can be reserved for you.",
        )
    if request.online_available:
        offer(
            Method.HOME_DELIVERY,
            SCORE_HOME_DELIVERY_WITH_STOCK if stock_ready else SCORE_HOME_DELIVERY_WITHOUT_STOCK,
            0,
            "This option is available for home delivery after your visit.",
        )

    if not stock_ready:
        reason = unmet_reason(request, policy)
        offer(
            Method.ALTERNATIVE_PRODUCT,
            SCORE_ALTERNATIVE_PRODUCT,
            0,
            (
                "The requested item is unavailable here; a similar option is available sooner."
                if reason is UnmetReason.NO_STOCK
                else "The requested item needs a stock check; a similar option can be "
                "considered sooner."
            ),
            reason_codes=(reason.value,) if reason else (),
        )

    if not options:
        # §7.5: an unfulfillable request is a record, not a silence. The reason
        # is machine-readable so unmet demand becomes a fact row rather than a
        # sentence somebody has to read.
        reason = unmet_reason(request, policy) or UnmetReason.NO_ENABLED_METHOD
        options.append(
            FulfilmentOption(
                method=Method.UNABLE_TO_FULFIL,
                score=SCORE_UNABLE,
                estimate="Unavailable",
                explanation="No enabled fulfilment route is currently available for this request.",
                reason_codes=(reason.value,),
            )
        )

    # Sort before the override, so the override is visibly the last word.
    # `-score` then `method` keeps ties deterministic: without the tiebreak two
    # equally-scored routes would order by insertion, which is an implementation
    # detail leaking into a golden test.
    options.sort(key=lambda o: (-o.score, o.method.value))
    return _apply_accessibility_override(request, policy, options)


def _offer_stocked_routes(
    request: FulfilmentRequest,
    policy: RetailerPolicy,
    offer: Any,
    direct_minutes: int,
) -> None:
    staff_allowed = request.capacity is not Capacity.RED or request.accessibility_need
    if request.capacity is Capacity.GREEN:
        staff_score = SCORE_STAFF_DELIVERY_GREEN
    elif request.capacity is Capacity.AMBER:
        staff_score = SCORE_STAFF_DELIVERY_AMBER
    else:
        staff_score = SCORE_STAFF_DELIVERY_ACCESSIBILITY

    if request.accessibility_need:
        staff_explanation = "Prioritised to support your accessibility need."
    elif request.capacity is Capacity.GREEN:
        staff_explanation = "A colleague can bring a confirmed item to your room now."
    else:
        staff_explanation = (
            "Available with an estimated delivery time based on current floor activity."
        )

    offer(
        Method.STAFF_DELIVERY_NOW,
        staff_score,
        direct_minutes,
        staff_explanation,
        available=staff_allowed,
        reason_codes=("accessibility_need",) if request.accessibility_need else (),
    )
    offer(
        Method.COMPANION_COLLECTION,
        SCORE_COMPANION_GREEN
        if request.capacity is Capacity.GREEN
        else SCORE_COMPANION_CONSTRAINED,
        direct_minutes,
        "Your companion can collect a confirmed item while you keep trying on.",
        available=request.companion_present,
    )
    offer(
        Method.CUSTOMER_SELF_COLLECTION,
        SCORE_SELF_COLLECTION_RED if request.capacity is Capacity.RED else SCORE_SELF_COLLECTION,
        direct_minutes,
        "The item can be collected from a nearby point when it suits you.",
    )
    offer(
        Method.BATCH_PICK,
        SCORE_BATCH_AMBER if request.capacity is Capacity.AMBER else SCORE_BATCH,
        direct_minutes + policy.batch_window_minutes,
        f"This item can travel with another pick in the next "
        f"{policy.batch_window_minutes}-minute collection window.",
        available=request.batch_opportunity,
    )
    offer(
        Method.BRING_BEFORE_I_FINISH,
        SCORE_BEFORE_I_FINISH_PREFERRED
        if request.timing_preference is TimingPreference.BEFORE_I_FINISH
        else SCORE_BEFORE_I_FINISH,
        direct_minutes + 3,
        "The request is timed to arrive before you finish your current session.",
    )
    offer(
        Method.COLLECT_AT_CHECKOUT,
        SCORE_CHECKOUT_PREFERRED
        if request.timing_preference is TimingPreference.NO_RUSH
        else SCORE_CHECKOUT,
        direct_minutes + 5,
        "The item can be held for collection when you reach checkout.",
    )


def _apply_accessibility_override(
    request: FulfilmentRequest,
    policy: RetailerPolicy,
    options: list[FulfilmentOption],
) -> list[FulfilmentOption]:
    """docs/product-spec.md §7.4 — restore staff delivery at Red.

    An availability rule, not a ranking one. It runs after the routes are
    assembled rather than as a clause inside the availability expression, so an
    edit to that expression cannot drop it without this function noticing that
    the route is missing.

    It deliberately does not hoist the route to first place. Doing so would
    change behaviour at Amber, where the prototype ranks a batched pick above
    staff delivery, and at Red with a companion present, where companion
    collection outranks it. Both are shipped behaviour; see the module
    docstring.
    """
    if not request.accessibility_need:
        return options
    if request.capacity is not Capacity.RED:
        # The route was never withheld above Red, so there is nothing to
        # restore. Applying the rule anyway would silently re-rank Green and
        # Amber, which §7.4 does not ask for.
        return options
    if not policy.enables(Method.STAFF_DELIVERY_NOW):
        # A retailer that disabled the method entirely made a policy decision
        # the override does not overrule; it cannot offer a route that does not
        # exist. The request still produces a record.
        return options
    if not stock_is_usable(request, policy):
        # Nothing to deliver. Offering the route would promise stock the
        # retailer does not believe it has.
        return options

    if any(o.method is Method.STAFF_DELIVERY_NOW for o in options):
        return options

    # The route was withheld and the rule says it should not have been. This is
    # the branch that fires if somebody edits the availability expression above.
    restored = FulfilmentOption(
        method=Method.STAFF_DELIVERY_NOW,
        score=SCORE_STAFF_DELIVERY_ACCESSIBILITY,
        estimate=_estimate(
            max(2, request.walking_minutes + (3 if request.location is Location.STOCKROOM else 1)),
            policy,
        ),
        explanation="Prioritised to support your accessibility need.",
        reason_codes=("accessibility_need",),
    )
    options.append(restored)
    options.sort(key=lambda o: (-o.score, o.method.value))
    return options
