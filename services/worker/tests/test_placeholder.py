"""Worker has no behaviour until Phase C.

This asserts the package imports and is versioned, so the package layout and
the uv workspace wiring are covered by CI from Phase A rather than first
being exercised when the Temporal client arrives.
"""

from __future__ import annotations

import fitos_worker


def test_package_imports_and_is_versioned() -> None:
    assert fitos_worker.__version__ == "0.0.0"
