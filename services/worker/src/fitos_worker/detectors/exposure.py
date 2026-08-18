"""The exposure model.

The rule from CLAUDE.md: *no modelled money without low, base, high, assumptions
and confidence.* This module is the only place exposure is computed, and it is
built so that producing a bare number is not possible — `Exposure` cannot be
constructed without all four, and the type system says so.

That matters more than it sounds. The failure this prevents is not somebody
maliciously inventing a figure; it is a well-meaning `exposure = count * margin`
appearing in a detector, being correct in isolation, and arriving in front of a
finance director as a precise-looking pound value that nobody can decompose.

Three rules, each from gap-model.md §3:

**Exposure is bounded by observability.** If any input is modelled rather than
observed, the whole exposure is modelled and is labelled so. There is no
partially-observed exposure: the weakest input sets the character of the answer.

**A wide interval is a confidence statement.** `high / low` above the configured
limit (default 5x) forces the band to `low` and adds `wide_exposure_interval`.
An interval that wide is the model saying it does not know, and presenting it
next to a confident band would contradict its own arithmetic.

**Exposure is not a savings claim.** The copy is "estimated exposure", never
"potential savings". `Exposure.describe()` produces the sanctioned phrasing so
the wording is not re-invented per surface, and a test asserts the forbidden
words never appear.

Every figure is integer minor units. Money never touches a float here: binary
floating point cannot represent 19.99, and an exposure figure is exactly the
kind of number people quote back at you.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from fitos_worker.detectors.confidence import WIDE_INTERVAL_RATIO, ConfidenceBand


class InputKind(StrEnum):
    """Where a number came from. This is what makes an exposure honest."""

    OBSERVED = "observed"
    GOVERNED_METRIC = "governed_metric"
    ASSUMPTION = "assumption"


@dataclass(frozen=True)
class ExposureInput:
    """One factor in an exposure formula, with its provenance.

    `low`, `base` and `high` are all required even for an observed input, where
    they are equal. Allowing a scalar would make the three-point structure
    optional in practice, and the first modelled input to arrive as a scalar
    would collapse the interval without anybody noticing.
    """

    key: str
    statement: str
    low: Decimal
    base: Decimal
    high: Decimal
    kind: InputKind
    source: str

    def __post_init__(self) -> None:
        if not (self.low <= self.base <= self.high):
            raise ValueError(
                f"{self.key}: low <= base <= high is required, got "
                f"{self.low}, {self.base}, {self.high}"
            )

    @property
    def is_modelled(self) -> bool:
        return self.kind is not InputKind.OBSERVED

    def as_assumption(self) -> dict[str, str]:
        """The assumption record stored on the gap.

        Every input becomes one, observed included: "this was measured exactly"
        is as much a part of explaining a figure as "we assumed 35%".
        """
        return {
            "key": self.key,
            "statement": self.statement,
            "value": f"{self.low}..{self.high} (base {self.base})",
            "source": self.source,
            "kind": self.kind.value,
        }


class ExposureError(ValueError):
    """An exposure that cannot be stated honestly is not stated at all."""


@dataclass(frozen=True)
class Exposure:
    """A three-point money estimate with its assumptions and confidence.

    Constructing one without all four is impossible: there is no default for
    `assumptions`, no default for `confidence_band`, and `low`/`base`/`high` are
    required positionally. That is deliberate — the invariant is easier to keep
    when the type will not let you break it.
    """

    low_minor: int
    base_minor: int
    high_minor: int
    currency: str
    formula_key: str
    formula_version: int
    assumptions: tuple[dict[str, str], ...]
    confidence_band: ConfidenceBand
    is_modelled: bool
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not (self.low_minor <= self.base_minor <= self.high_minor):
            raise ExposureError(
                f"exposure must be ordered: {self.low_minor}, {self.base_minor}, {self.high_minor}"
            )
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise ExposureError(f"{self.currency!r} is not an ISO 4217 code")
        if not self.assumptions:
            # The rule, enforced at construction. An exposure whose inputs are
            # not recorded cannot be argued with, which is the same as not
            # being able to be trusted.
            raise ExposureError(
                "exposure requires at least one assumption; a figure whose inputs "
                "are not recorded cannot be checked"
            )

    def describe(self) -> str:
        """The sanctioned phrasing.

        Centralised so the wording is not re-invented per surface. "Estimated
        exposure", never "potential savings" — the second is a claim about
        money that would be recovered, which nothing here establishes.
        """
        low = self.low_minor / 100
        high = self.high_minor / 100
        return (
            f"Estimated exposure {self.currency} {low:,.2f}–{high:,.2f} "  # noqa: RUF001
            f"({self.confidence_band.value} confidence)"
        )

    def as_gap_fields(self) -> dict[str, object]:
        """The columns this maps to on the Gap aggregate."""
        return {
            "exposure_low": self.low_minor,
            "exposure_base": self.base_minor,
            "exposure_high": self.high_minor,
            "currency": self.currency,
            "assumptions": list(self.assumptions),
            "confidence_band": self.confidence_band.value,
        }


def _to_minor(amount: Decimal) -> int:
    """Decimal to integer minor units, half-up.

    Never through a float. `int(19.99 * 100)` is 1998, and an exposure figure is
    exactly the kind of number somebody quotes back at you.
    """
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_exposure(
    *,
    inputs: list[ExposureInput],
    currency: str,
    formula_key: str,
    formula_version: int,
    confidence_band: ConfidenceBand,
    wide_interval_ratio: float = WIDE_INTERVAL_RATIO,
) -> Exposure:
    """Multiply the inputs three ways and return the interval.

    `low` uses every input's low, `high` uses every high. That is deliberately
    the *widest* honest interval rather than a statistical combination: the
    inputs are not independent samples, and treating them as if they were would
    narrow the range on an assumption nobody has justified. A wide interval that
    is honest beats a narrow one that is invented.
    """
    if not inputs:
        raise ExposureError("an exposure needs at least one input")

    low = Decimal(1)
    base = Decimal(1)
    high = Decimal(1)
    for factor in inputs:
        low *= factor.low
        base *= factor.base
        high *= factor.high

    # If any input is modelled, the whole exposure is modelled. There is no
    # partially-observed money: the weakest input sets the character of the
    # answer, and labelling it otherwise would overstate what is known.
    is_modelled = any(factor.is_modelled for factor in inputs)

    low_minor = _to_minor(low)
    base_minor = _to_minor(base)
    high_minor = _to_minor(high)

    band = confidence_band
    reason_codes: list[str] = []
    if low_minor > 0 and high_minor / low_minor > wide_interval_ratio:
        # The arithmetic is saying it does not know. Presenting a confident
        # band beside it would contradict the interval it sits next to.
        band = ConfidenceBand.LOW
        reason_codes.append("wide_exposure_interval")

    if is_modelled:
        reason_codes.append("modelled_exposure")

    return Exposure(
        low_minor=low_minor,
        base_minor=base_minor,
        high_minor=high_minor,
        currency=currency.upper(),
        formula_key=formula_key,
        formula_version=formula_version,
        assumptions=tuple(factor.as_assumption() for factor in inputs),
        confidence_band=band,
        is_modelled=is_modelled,
        reason_codes=tuple(reason_codes),
    )


def observed(key: str, statement: str, value: Decimal, source: str) -> ExposureInput:
    """An exactly-measured input. Low, base and high are all the same."""
    return ExposureInput(
        key=key,
        statement=statement,
        low=value,
        base=value,
        high=value,
        kind=InputKind.OBSERVED,
        source=source,
    )


def assumed(
    key: str,
    statement: str,
    *,
    low: Decimal,
    base: Decimal,
    high: Decimal,
    source: str,
) -> ExposureInput:
    """A tenant assumption, recorded as such.

    `recovery_probability` is the canonical example: it is not an observation,
    and changing it is an admin action that writes an audit record. It never
    silently changes historical gap values, because `formula_version` pins them.
    """
    return ExposureInput(
        key=key,
        statement=statement,
        low=low,
        base=base,
        high=high,
        kind=InputKind.ASSUMPTION,
        source=source,
    )


def from_governed_metric(
    key: str,
    statement: str,
    *,
    p25: Decimal,
    median: Decimal,
    p75: Decimal,
    metric_identity: str,
) -> ExposureInput:
    """A distribution from a governed metric, as its quartiles.

    The interquartile range rather than a mean: a single central value would
    hide the spread, and the spread is most of what an exposure interval is
    trying to communicate.
    """
    return ExposureInput(
        key=key,
        statement=statement,
        low=p25,
        base=median,
        high=p75,
        kind=InputKind.GOVERNED_METRIC,
        source=metric_identity,
    )
