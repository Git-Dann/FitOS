"""Applying a mapping version to source records.

A mapping is data, not code, which is what lets it be versioned, previewed,
compared and rolled back without a deploy. This module is the interpreter.

The rule the whole design serves: **corrections happen forward**. A wrong value
is fixed by a new mapping version and a re-run, never by editing raw data or
overwriting a canonical row. So `apply` is a pure function of (mapping, record)
— given the same version and the same raw object, it produces the same staging
row today and in two years, which is what makes a gap's evidence reproducible
long after the mapping has moved on.

Transforms are a small closed set rather than an expression language. An
expression language here would be a remote code execution surface configured by
whoever can edit a connection, and "it is only a formula" is exactly how that
gets shipped. If a source needs something the set does not cover, that is a
connector change with a code review, not a config change.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fitos_connector_sdk.quarantine import QualityFlag, QuarantineReason

# The closed set. Adding one is a deliberate contract change.
TRANSFORMS = frozenset(
    {
        "trim",
        "lower",
        "upper",
        "to_int",
        "to_decimal",
        "to_timestamp",
        "to_minor_units",
        "nullify_empty",
    }
)


class UnknownTransformError(ValueError):
    """A mapping named a transform that does not exist.

    Refused at save time rather than silently ignored at run time: a mapping
    with a typo that quietly does nothing produces plausible wrong numbers,
    which is worse than an error.
    """


@dataclass(frozen=True)
class MappingSpec:
    """The version, as the interpreter sees it."""

    version: int
    target_table: str
    column_map: Mapping[str, str]
    required_columns: tuple[str, ...] = ()
    transforms: Mapping[str, list[str]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(self, "transforms", dict(self.transforms or {}))
        for column, names in self.transforms.items():
            for name in names:
                if name not in TRANSFORMS:
                    raise UnknownTransformError(
                        f"{column}: unknown transform {name!r}; "
                        f"expected one of {sorted(TRANSFORMS)}"
                    )


@dataclass(frozen=True)
class MappedRow:
    """The outcome of applying a mapping to one record.

    Either `row` is populated or `reasons` is; never both, and never neither.
    A partial row with a reason attached is the shape that leads to half-mapped
    data being written and counted as success.
    """

    row: dict[str, Any] | None
    reasons: tuple[QuarantineReason, ...]

    @property
    def ok(self) -> bool:
        return self.row is not None


def apply_mapping(spec: MappingSpec, payload: Mapping[str, Any]) -> MappedRow:
    """Map one source record. Never raises on bad data; returns reasons instead.

    A source record is untrusted input arriving in bulk. An exception here would
    abort a run of 200,000 records because one of them had a bad date, which is
    the opposite of what quarantine is for.
    """
    reasons: list[QuarantineReason] = []
    row: dict[str, Any] = {}

    for target, source in spec.column_map.items():
        value: Any = payload.get(source)

        for name in spec.transforms.get(target, []):
            value, problem = _transform(name, value, field=target)
            if problem is not None:
                reasons.append(problem)
                value = None
                break

        row[target] = value

    for column in spec.required_columns:
        if row.get(column) is None or (isinstance(row[column], str) and not row[column].strip()):
            reasons.append(
                QuarantineReason(
                    flag=QualityFlag.MISSING_REQUIRED,
                    field=column,
                    detail=f"{column} is required by mapping version {spec.version}",
                )
            )

    # A column the mapping references but the source never sent is schema drift,
    # and it is reported as such rather than as a missing value — the two have
    # different fixes, and conflating them sends people to the wrong one.
    for target, source in spec.column_map.items():
        if source not in payload:
            reasons.append(
                QuarantineReason(
                    flag=QualityFlag.SCHEMA_DRIFT,
                    field=target,
                    detail=f"the source did not supply {source!r}",
                )
            )

    if reasons:
        return MappedRow(row=None, reasons=tuple(reasons))
    return MappedRow(row=row, reasons=())


def _transform(name: str, value: Any, *, field: str) -> tuple[Any, QuarantineReason | None]:
    if value is None:
        return None, None

    text = str(value)

    if name == "trim":
        return text.strip(), None
    if name == "lower":
        return text.lower(), None
    if name == "upper":
        return text.upper(), None
    if name == "nullify_empty":
        return (None if not text.strip() else text), None

    if name == "to_int":
        try:
            return int(text.strip()), None
        except (ValueError, TypeError):
            return None, QuarantineReason(
                flag=QualityFlag.TYPE_COERCED, field=field, detail=f"{text!r} is not an integer"
            )

    if name == "to_decimal":
        try:
            return Decimal(text.strip()), None
        except (InvalidOperation, ValueError, TypeError):
            return None, QuarantineReason(
                flag=QualityFlag.TYPE_COERCED, field=field, detail=f"{text!r} is not a number"
            )

    if name == "to_minor_units":
        # Money is stored in minor units as an integer. Doing this with floats
        # is how 19.99 becomes 1998: Decimal, then quantise, then int.
        try:
            amount = Decimal(text.strip())
        except (InvalidOperation, ValueError, TypeError):
            return None, QuarantineReason(
                flag=QualityFlag.TYPE_COERCED, field=field, detail=f"{text!r} is not an amount"
            )
        return int((amount * 100).quantize(Decimal("1"))), None

    if name == "to_timestamp":
        parsed = _parse_timestamp(text)
        if parsed is None:
            return None, QuarantineReason(
                flag=QualityFlag.TYPE_COERCED,
                field=field,
                detail=f"{text!r} is not an ISO-8601 timestamp",
            )
        return parsed, None

    # Unreachable: MappingSpec refuses an unknown transform at construction.
    raise UnknownTransformError(name)


def _parse_timestamp(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


@dataclass(frozen=True)
class MappingDiff:
    """What changed between two versions, for the compare view.

    Structured rather than a text diff, because the question being asked is
    "what will this do to my numbers", and a textual diff of JSON answers a
    different question.
    """

    added_columns: tuple[str, ...]
    removed_columns: tuple[str, ...]
    changed_columns: tuple[tuple[str, str, str], ...]
    added_required: tuple[str, ...]
    removed_required: tuple[str, ...]
    changed_transforms: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not (
            self.added_columns
            or self.removed_columns
            or self.changed_columns
            or self.added_required
            or self.removed_required
            or self.changed_transforms
        )


def diff_mappings(before: MappingSpec, after: MappingSpec) -> MappingDiff:
    before_columns = dict(before.column_map)
    after_columns = dict(after.column_map)

    changed = tuple(
        (target, before_columns[target], after_columns[target])
        for target in sorted(set(before_columns) & set(after_columns))
        if before_columns[target] != after_columns[target]
    )

    before_required = set(before.required_columns)
    after_required = set(after.required_columns)

    transforms_changed = tuple(
        sorted(
            column
            for column in set(before.transforms) | set(after.transforms)
            if before.transforms.get(column, []) != after.transforms.get(column, [])
        )
    )

    return MappingDiff(
        added_columns=tuple(sorted(set(after_columns) - set(before_columns))),
        removed_columns=tuple(sorted(set(before_columns) - set(after_columns))),
        changed_columns=changed,
        added_required=tuple(sorted(after_required - before_required)),
        removed_required=tuple(sorted(before_required - after_required)),
        changed_transforms=transforms_changed,
    )


@dataclass(frozen=True)
class PreviewResult:
    """What a mapping would do, without doing it.

    Preview runs the real `apply_mapping` over real sampled records. A preview
    that approximates the mapping is a preview that lies at exactly the moment
    somebody needs it — before applying a change to production data.
    """

    sampled: int
    would_write: int
    would_quarantine: int
    rows: tuple[dict[str, Any], ...]
    rejections: tuple[tuple[str, tuple[QuarantineReason, ...]], ...]

    @property
    def rejection_rate(self) -> float:
        return self.would_quarantine / self.sampled if self.sampled else 0.0


def preview(
    spec: MappingSpec,
    # Sequence, not list: preview never mutates, and list is invariant, so a
    # caller holding list[tuple[str, dict[...]]] could not pass it otherwise.
    records: Sequence[tuple[str, Mapping[str, Any]]],
    *,
    limit: int = 20,
) -> PreviewResult:
    """Apply the mapping to sampled records and report what would happen."""
    rows: list[dict[str, Any]] = []
    rejections: list[tuple[str, tuple[QuarantineReason, ...]]] = []

    for record_id, payload in records:
        result = apply_mapping(spec, payload)
        if result.ok and result.row is not None:
            if len(rows) < limit:
                rows.append(result.row)
        else:
            if len(rejections) < limit:
                rejections.append((record_id, result.reasons))

    written = sum(1 for _, payload in records if apply_mapping(spec, payload).ok)

    return PreviewResult(
        sampled=len(records),
        would_write=written,
        would_quarantine=len(records) - written,
        rows=tuple(rows),
        rejections=tuple(rejections),
    )
