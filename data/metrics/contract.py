"""The governed metric contract.

One definition, three consumers. A metric is declared once here and the Cube
model, the API's SQL and the dbt test are all *generated* from it — never
hand-written alongside it. Three hand-maintained copies of a formula agree right
up until the moment somebody edits one, and the failure is silent: the number on
the dashboard, the number in the export and the number in the alert quietly
diverge, and nobody can say which is right.

That is the whole point of the acceptance criterion this serves: *a certified
metric returns the same value through Cube, the API and a dbt test*. It is only
testable because there is one source.

Three rules are structural rather than advisory:

**A formula exists once.** `measure_expression` is the single place a metric's
arithmetic is written. Nothing downstream re-implements it, and a React
component may not contain one at all.

**Versions are immutable.** Changing a formula increments `version` and sets
`valid_to` on the old one. Old versions stay resolvable forever, because a gap
references `metric_version` and its evidence must remain reproducible years
later. Editing a formula in place would retroactively change every gap it ever
raised.

**Certification is earned.** A metric with no owner and no quality tests cannot
be certified, and only certified metrics are exposed to the product, the API and
the AI layer. `is_certified` is computed from those facts rather than set by
hand, so it cannot be granted by editing a flag.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFINITIONS_DIR = Path(__file__).resolve().parent / "definitions"


class Unit(StrEnum):
    COUNT = "count"
    RATIO = "ratio"
    CURRENCY_MINOR = "currency_minor"
    SECONDS = "seconds"


class CurrencyPolicy(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    ORGANIZATION_DEFAULT = "organization_default"
    PER_ROW = "per_row"


class Sensitivity(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class NullPolicy(StrEnum):
    EXCLUDE_NULL_DENOMINATOR = "exclude_null_denominator"
    ZERO_AS_NULL = "zero_as_null"
    PROPAGATE = "propagate"


class QualityTest(StrEnum):
    """The closed set of quality tests a metric may declare.

    Closed because each one has to be *executable* — it compiles to a dbt test
    and to a golden assertion. A free-text quality test is a comment.
    """

    NOT_NULL = "not_null"
    BETWEEN_0_AND_1 = "between_0_and_1"
    NON_NEGATIVE = "non_negative"
    DENOMINATOR_MIN_30 = "denominator_min_30"
    MONOTONIC_NON_DECREASING = "monotonic_non_decreasing"


# A measure expression is SQL, and SQL is where a metric layer becomes an
# injection surface. These are refused outright: a metric definition is
# authored in the repository and reviewed, but it is also the most attractive
# thing in the system to smuggle a statement into.
FORBIDDEN_SQL = re.compile(
    r"(;|--|/\*|\bdrop\b|\bdelete\b|\btruncate\b|\balter\b|\bgrant\b|\brevoke\b|\binsert\b|"
    r"\bupdate\b|\battach\b|\bsystem\b|\bfile\s*\(|\burl\s*\()",
    re.IGNORECASE,
)


class MetricExample(BaseModel):
    """An executable example. These are the metric's golden tests.

    Not documentation: `expected` is asserted against the real query. An example
    that is never run is a comment that ages badly, and a metric layer full of
    stale comments is worse than one with none.
    """

    model_config = ConfigDict(extra="forbid")

    filters: dict[str, str] = Field(default_factory=dict)
    expected: float
    # Ratios and money rarely land on an exact float. The tolerance is declared
    # per example rather than assumed globally, because "close enough" differs
    # between a count (exact) and a margin (fractions of a penny).
    tolerance: float = 0.0


class JoinPath(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_model: str = Field(alias="from")
    to_model: str = Field(alias="to")
    on: str

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class MetricDefinition(BaseModel):
    """One governed metric. The single source for Cube, the API and dbt."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z][a-z0-9_]{2,62}$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=10)
    owner: str = Field(min_length=1)
    version: int = Field(ge=1)

    grain: list[str] = Field(min_length=1)
    measure_expression: str = Field(min_length=1)
    dimensions: list[str] = Field(default_factory=list)
    allowed_filters: list[str] = Field(default_factory=list)
    source_models: list[str] = Field(min_length=1)
    join_paths: list[JoinPath] = Field(default_factory=list)

    unit: Unit
    currency_policy: CurrencyPolicy = CurrencyPolicy.NOT_APPLICABLE
    timezone_policy: str = "organization_display_timezone"
    null_policy: NullPolicy = NullPolicy.PROPAGATE

    valid_from: date
    valid_to: date | None = None

    sensitivity: Sensitivity = Sensitivity.INTERNAL
    quality_tests: list[QualityTest] = Field(default_factory=list)
    examples: list[MetricExample] = Field(default_factory=list)

    # Set by the pack that owns the metric. Exposure-bearing metrics are
    # withheld from frontline tokens server-side (gap-model.md §3).
    is_exposure_bearing: bool = False

    @field_validator("measure_expression")
    @classmethod
    def _expression_is_a_single_expression(cls, value: str) -> str:
        if FORBIDDEN_SQL.search(value):
            raise ValueError(
                "measure_expression must be a single SQL expression: no statement "
                "separators, comments, DDL, DML or table functions"
            )
        return value.strip()

    @model_validator(mode="after")
    def _filters_are_dimensions(self) -> MetricDefinition:
        unknown = set(self.allowed_filters) - set(self.dimensions) - set(self.grain)
        if unknown:
            # A filter the metric cannot group by is a filter that silently does
            # nothing, or worse, one that changes the denominator without
            # changing the numerator.
            raise ValueError(
                f"allowed_filters names things that are neither dimensions nor grain: "
                f"{sorted(unknown)}"
            )
        return self

    @model_validator(mode="after")
    def _money_declares_a_currency_policy(self) -> MetricDefinition:
        if self.unit is Unit.CURRENCY_MINOR and self.currency_policy is (
            CurrencyPolicy.NOT_APPLICABLE
        ):
            raise ValueError(
                "a currency_minor metric must declare a currency_policy; "
                "summing minor units across currencies is meaningless"
            )
        return self

    @model_validator(mode="after")
    def _a_ratio_declares_its_bounds(self) -> MetricDefinition:
        if self.unit is Unit.RATIO and QualityTest.BETWEEN_0_AND_1 not in self.quality_tests:
            # A ratio that can exceed 1 is usually a join fan-out, and it is the
            # single most common way a metric layer produces a confidently
            # wrong number.
            raise ValueError(
                "a ratio metric must declare the between_0_and_1 quality test; "
                "a ratio above 1 is usually a join fan-out"
            )
        return self

    @property
    def is_certified(self) -> bool:
        """Computed, never set.

        Certification cannot be granted by editing a flag: it follows from
        having an owner, executable examples and quality tests, which are the
        things that make a metric trustworthy in the first place.
        """
        return bool(self.owner) and bool(self.quality_tests) and bool(self.examples)

    @property
    def certification_gaps(self) -> list[str]:
        """Why this metric is not certified. Empty when it is."""
        missing = []
        if not self.owner:
            missing.append("owner")
        if not self.quality_tests:
            missing.append("quality_tests")
        if not self.examples:
            missing.append("examples")
        return missing

    @property
    def identity(self) -> str:
        """Stable identity for evidence: the key and version together.

        A gap references this. Two metrics with the same key and different
        versions are different metrics as far as evidence is concerned.
        """
        return f"{self.key}@v{self.version}"

    def query_hash(self, *, grain: list[str] | None = None) -> str:
        """Hash of the compiled query, recorded on every piece of evidence.

        Includes the version and the expression, so a formula change produces a
        different hash and old evidence remains attributable to the query that
        actually produced it.
        """
        material = "|".join(
            [
                self.key,
                str(self.version),
                self.measure_expression,
                ",".join(sorted(self.source_models)),
                ",".join(grain or self.grain),
            ]
        )
        return hashlib.sha256(material.encode()).hexdigest()

    def is_valid_on(self, when: date) -> bool:
        if when < self.valid_from:
            return False
        return self.valid_to is None or when < self.valid_to


class MetricRegistry:
    """Every metric definition, loaded once and validated as a set.

    A set rather than a list, because two of the rules are cross-definition:
    a key may have only one version live at a time, and a superseded version
    must actually have been superseded.
    """

    def __init__(self, definitions: list[MetricDefinition]) -> None:
        self._by_identity = {d.identity: d for d in definitions}
        self._validate_set(definitions)
        self.definitions = definitions

    @staticmethod
    def _validate_set(definitions: list[MetricDefinition]) -> None:
        seen: dict[str, list[MetricDefinition]] = {}
        for definition in definitions:
            seen.setdefault(definition.key, []).append(definition)

        for key, versions in seen.items():
            numbers = [d.version for d in versions]
            if len(numbers) != len(set(numbers)):
                raise ValueError(f"{key}: duplicate version numbers {sorted(numbers)}")

            open_ended = [d for d in versions if d.valid_to is None]
            if len(open_ended) > 1:
                # Two live versions means two answers to "what is this metric",
                # and whichever one a consumer happens to pick becomes the truth.
                raise ValueError(
                    f"{key}: {len(open_ended)} versions have no valid_to; "
                    "exactly one version may be live"
                )

    @classmethod
    def load(cls, directory: Path | None = None) -> MetricRegistry:
        path = directory or DEFINITIONS_DIR
        definitions = []
        for file in sorted(path.glob("*.yml")):
            # safe_load, never load. A metric definition is a file in the
            # repository, but the difference costs nothing and the habit is what
            # matters (threat-model T10).
            raw = yaml.safe_load(file.read_text())
            try:
                definitions.append(MetricDefinition.model_validate(raw))
            except Exception as exc:
                raise ValueError(f"{file.name}: {exc}") from exc
        return cls(definitions)

    def get(self, key: str, version: int | None = None) -> MetricDefinition:
        """Fetch a metric. Without a version, the live one.

        Asking for a specific version always works, including for superseded
        ones, because evidence has to stay resolvable.
        """
        candidates = [d for d in self.definitions if d.key == key]
        if not candidates:
            raise KeyError(f"no metric named {key!r}")

        if version is not None:
            for candidate in candidates:
                if candidate.version == version:
                    return candidate
            raise KeyError(f"{key} has no version {version}")

        live = [d for d in candidates if d.valid_to is None]
        if not live:
            raise KeyError(f"{key} has no live version")
        return live[0]

    def certified(self) -> list[MetricDefinition]:
        return [d for d in self.definitions if d.is_certified]

    def __len__(self) -> int:
        return len(self.definitions)

    def __iter__(self) -> Any:
        return iter(self.definitions)
