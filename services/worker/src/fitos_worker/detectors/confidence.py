"""The confidence model.

`confidence_score` is a weighted product of component scores, each in 0..1, each
stored so the UI can show the breakdown and the AI layer can *explain* it —
never set it. That distinction is the whole reason this is arithmetic in a
module rather than a judgement made anywhere else: a confidence a model can
influence is a confidence that can be talked upward.

Three rules from gap-model.md §4 are implemented here, and each exists because
of a specific way a confidence score becomes a lie:

**Components that do not apply are dropped and the weights renormalised**, with
the dropped set recorded. Scoring an inapplicable component as 0 would punish a
detector for a measurement that was never relevant; scoring it as 1 would
reward it for the same. Dropping and renormalising is the only honest option,
and recording what was dropped is what makes the score auditable.

**A weak component caps the band.** Any component below 0.2 caps at `medium`;
below 0.1 caps at `low`. Without this, six strong components drown one terrible
one and a gap built on a 5% complete dataset presents as high confidence — the
weighted mean is exactly the wrong summary when one input is disqualifying.

**Attribution-based gaps are capped at `medium` by construction**, with reason
code `attribution_limited`. A correlation between spend and outcome does not
establish the link, and no amount of sample size changes that. This is a hard
rule, not a heuristic, so it is applied after every other calculation and
cannot be outvoted.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ConfidenceBand(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Component(StrEnum):
    SAMPLE_SIZE = "sample_size"
    COMPLETENESS = "completeness"
    FRESHNESS = "freshness"
    SOURCE_AGREEMENT = "source_agreement"
    METRIC_STABILITY = "metric_stability"
    DETECTOR_FIT = "detector_fit"
    IDENTITY_MATCH = "identity_match"


# From gap-model.md §4. Weights sum to 1.0 when every component applies.
DEFAULT_WEIGHTS: dict[Component, float] = {
    Component.SAMPLE_SIZE: 0.20,
    Component.COMPLETENESS: 0.20,
    Component.FRESHNESS: 0.15,
    Component.SOURCE_AGREEMENT: 0.15,
    Component.METRIC_STABILITY: 0.10,
    Component.DETECTOR_FIT: 0.15,
    Component.IDENTITY_MATCH: 0.05,
}

# A single component this weak disqualifies the whole score from the band above.
CAP_TO_MEDIUM_BELOW = 0.2
CAP_TO_LOW_BELOW = 0.1

BAND_LOW_CEILING = 0.4
BAND_HIGH_FLOOR = 0.7

# gap-model.md §3: a wide interval is itself a statement about confidence.
WIDE_INTERVAL_RATIO = 5.0


@dataclass(frozen=True)
class ConfidenceResult:
    """The score, the band, and everything needed to explain both.

    `components` and `dropped` are stored on the gap's evidence so the breakdown
    is inspectable. A score with no breakdown is a number the product asks
    people to trust for no stated reason.
    """

    score: float
    band: ConfidenceBand
    components: dict[str, float]
    weights: dict[str, float]
    dropped: tuple[str, ...]
    caps_applied: tuple[str, ...]
    reason_codes: tuple[str, ...]


def _band_for(score: float) -> ConfidenceBand:
    if score < BAND_LOW_CEILING:
        return ConfidenceBand.LOW
    if score > BAND_HIGH_FLOOR:
        return ConfidenceBand.HIGH
    return ConfidenceBand.MEDIUM


def _cap(band: ConfidenceBand, ceiling: ConfidenceBand) -> ConfidenceBand:
    order = [ConfidenceBand.LOW, ConfidenceBand.MEDIUM, ConfidenceBand.HIGH]
    return order[min(order.index(band), order.index(ceiling))]


def score_confidence(
    components: dict[Component, float],
    *,
    weights: dict[Component, float] | None = None,
    is_attribution_based: bool = False,
    exposure_low: int | None = None,
    exposure_high: int | None = None,
) -> ConfidenceResult:
    """Compute a confidence score and band from component scores.

    Only the components supplied are used. Anything absent is *dropped*, not
    assumed — see the module docstring for why that matters.
    """
    if not components:
        raise ValueError(
            "confidence requires at least one component; a gap with no measurable "
            "confidence must not be raised rather than defaulting to a number"
        )

    for name, value in components.items():
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} is {value}; component scores are in 0..1")

    base_weights = weights or DEFAULT_WEIGHTS
    applicable = {c: base_weights[c] for c in components if c in base_weights}
    if not applicable:
        raise ValueError("no supplied component has a weight")

    # Renormalise over what applies. Without this, dropping a component would
    # silently deflate the score toward zero simply because its weight vanished.
    total_weight = sum(applicable.values())
    normalised = {c: w / total_weight for c, w in applicable.items()}

    score = sum(components[c] * normalised[c] for c in normalised)
    band = _band_for(score)

    caps: list[str] = []
    reason_codes: list[str] = []

    weakest = min(components.values())
    if weakest < CAP_TO_LOW_BELOW:
        # One disqualifying input. A weighted mean is exactly the wrong summary
        # here: six strong components would otherwise drown it.
        band = _cap(band, ConfidenceBand.LOW)
        caps.append(f"component below {CAP_TO_LOW_BELOW}")
    elif weakest < CAP_TO_MEDIUM_BELOW:
        band = _cap(band, ConfidenceBand.MEDIUM)
        caps.append(f"component below {CAP_TO_MEDIUM_BELOW}")

    if (
        exposure_low is not None
        and exposure_high is not None
        and exposure_low > 0
        and exposure_high / exposure_low > WIDE_INTERVAL_RATIO
    ):
        # An interval this wide is a statement about how little is known,
        # regardless of how good the component scores look.
        band = _cap(band, ConfidenceBand.LOW)
        caps.append("wide exposure interval")
        reason_codes.append("wide_exposure_interval")

    if is_attribution_based:
        # Hard rule, applied last so nothing can outvote it. A correlation
        # between spend and outcome does not establish the link, and no sample
        # size changes that.
        band = _cap(band, ConfidenceBand.MEDIUM)
        caps.append("attribution-based")
        reason_codes.append("attribution_limited")

    dropped = tuple(sorted(c.value for c in base_weights if c not in components))

    return ConfidenceResult(
        score=round(score, 3),
        band=band,
        components={c.value: components[c] for c in sorted(components, key=lambda c: c.value)},
        weights={
            c.value: round(normalised[c], 4) for c in sorted(normalised, key=lambda c: c.value)
        },
        dropped=dropped,
        caps_applied=tuple(caps),
        reason_codes=tuple(reason_codes),
    )


@dataclass(frozen=True)
class SampleSizeScore:
    """Sample size against the detector's declared minimum.

    Linear up to the minimum and flat after: a detector that needs 30
    observations gains nothing from the 400th, and letting the score keep
    climbing would let a large sample paper over a weak component elsewhere.
    """

    observations: int
    minimum: int

    @property
    def value(self) -> float:
        if self.minimum <= 0:
            return 1.0
        return min(1.0, self.observations / self.minimum)

    @property
    def is_sufficient(self) -> bool:
        """The hard precondition. Below the minimum, no gap is raised at all.

        This is where `denominator_min_30` from the metric contract is actually
        enforced. It is deliberately not a dbt build failure — a small location
        having few observations is a correct value over few observations, not a
        broken pipeline — but it *is* a refusal to make a claim.
        """
        return self.observations >= self.minimum


def freshness_score(age_seconds: float, expected_latency_seconds: float) -> float:
    """Decay against the source's declared cadence.

    1.0 while inside the expected latency, then decaying. A source that is
    twice as late as it promised scores 0.5, and one ten times late scores 0.1 —
    it does not hit zero, because "very stale" and "absent" are different
    conditions and the second is a data-quality gap in its own right.
    """
    if expected_latency_seconds <= 0:
        return 1.0
    if age_seconds <= expected_latency_seconds:
        return 1.0
    return max(0.0, min(1.0, expected_latency_seconds / age_seconds))
