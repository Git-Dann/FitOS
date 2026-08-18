"""The pack contract.

docs/product-spec.md §5: *the core must not name "retail" anywhere outside
`packs/retail`*. Future packs exist only as a contract test, and this is it.

The rule is not stylistic. A detector class that hard-codes one domain's gap
type, copy or playbook ids is a class the second pack has to fork, and two forks
of a detector drift the moment either is fixed. Keeping the vocabulary in the
pack is what makes "adding a pack must not change core data contracts" true
rather than aspirational.

The check reads string *literals* rather than the raw file, deliberately.
Explanatory prose in a comment or docstring — "some discrepancy is normal in
any retail estate" — is not a pack dependency, and a grep-based check would
either flag it or be weakened until it flagged nothing. What matters is the
strings that reach data: gap types, playbook ids, configuration defaults.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]

# Everything that must stay pack-neutral.
CORE_ROOTS = (
    REPO / "services" / "api" / "src",
    REPO / "services" / "worker" / "src",
    REPO / "connectors",
    REPO / "data" / "canonical",
)

# Pack vocabulary. Lower-cased substring match against string literals.
PACK_WORDS = ("retail", "omnichannel", "fitting_room", "fitting-room")


def _string_literals(tree: ast.Module) -> list[tuple[int, str]]:
    """Every string constant that is not a docstring.

    Docstrings are prose about the code. A pack name in one is a comment; a
    pack name in a value is a dependency.
    """
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))

    found = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            found.append((node.lineno, node.value))
    return found


def _core_python_files() -> list[Path]:
    files: list[Path] = []
    for root in CORE_ROOTS:
        files.extend(
            path
            for path in root.rglob("*.py")
            if "__pycache__" not in path.parts and "tests" not in path.parts
        )
    return sorted(files)


def test_the_check_has_something_to_check() -> None:
    """A contract test over an empty file list passes everything.

    This is the failure CLAUDE.md names: a coverage check that finds nothing
    looks exactly like one that works.
    """
    files = _core_python_files()
    assert len(files) > 30, f"only found {len(files)} core files; the roots are probably wrong"


def test_the_core_names_no_pack() -> None:
    """docs/product-spec.md §5, as an executable rule."""
    offences: list[str] = []
    for path in _core_python_files():
        tree = ast.parse(path.read_text())
        for lineno, value in _string_literals(tree):
            lowered = value.lower()
            for word in PACK_WORDS:
                if word in lowered:
                    offences.append(
                        f"{path.relative_to(REPO)}:{lineno} contains {word!r}: {value!r}"
                    )
    assert not offences, "core code names a pack:\n" + "\n".join(offences)


def test_the_check_would_catch_a_pack_name_in_a_value() -> None:
    """The guard proved to discriminate, not assumed to.

    Without this, narrowing `PACK_WORDS` to nothing or breaking the AST walk
    would leave a test that passes on anything.
    """
    tree = ast.parse('x = "retail.stock_truth.recount"\n')
    literals = [v for _, v in _string_literals(tree)]
    assert any("retail" in v for v in literals)


def test_the_check_ignores_a_pack_name_in_prose() -> None:
    tree = ast.parse('"""Some discrepancy is normal in any retail estate."""\nx = 1\n')
    literals = [v for _, v in _string_literals(tree)]
    assert not any("retail" in v for v in literals)


# ---------------------------------------------------------------------------
# The pack supplies what the core does not
# ---------------------------------------------------------------------------


def test_the_retail_rule_configures_a_generic_detector() -> None:
    """The pack contributes vocabulary; the class stays in the core."""
    import uuid

    from fitos_pack_retail import PACK_KEY, stock_truth_rule
    from fitos_worker.detectors.source_mismatch import SourceMismatchDetector

    rule = stock_truth_rule(rule_id=uuid.UUID("11111111-1111-1111-1111-111111111111"))
    detector = SourceMismatchDetector(rule)

    assert rule.pack_key == PACK_KEY
    assert detector.gap_type == "stock_truth_mismatch"
    assert rule.action_playbook_id == "retail.stock_truth.recount"
    assert detector.key == "source_mismatch", "the class is not retail-specific"


def test_the_detector_class_has_no_pack_defaults() -> None:
    """`gap_type`, `canonical_entity` and the playbook id have no defaults.

    A default here would let a pack forget to set one and silently inherit
    another pack's vocabulary, which is worse than a startup error.
    """
    from fitos_worker.detectors.source_mismatch import SourceMismatchConfig

    with pytest.raises(ValueError, match="gap_type"):
        SourceMismatchConfig(  # type: ignore[call-arg]
            rule_id="11111111-1111-1111-1111-111111111111",  # type: ignore[arg-type]
            version=1,
            pack_key="p",
            canonical_entity="e",
            action_playbook_id="p.a",
        )


def test_two_packs_can_configure_the_same_class_differently() -> None:
    """The point of the contract: a second pack does not fork the detector."""
    import uuid

    from fitos_pack_retail import stock_truth_rule
    from fitos_worker.detectors.source_mismatch import (
        SourceMismatchConfig,
        SourceMismatchDetector,
    )

    retail = SourceMismatchDetector(stock_truth_rule(rule_id=uuid.uuid4()))
    venue = SourceMismatchDetector(
        SourceMismatchConfig(
            rule_id=uuid.uuid4(),
            version=1,
            pack_key="venue_operations",
            gap_type="capacity_record_mismatch",
            canonical_entity="fact_capacity_check",
            action_playbook_id="venue.capacity.recheck",
        )
    )

    assert retail.gap_type != venue.gap_type
    assert type(retail) is type(venue)
