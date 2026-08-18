"""The two guards that are easy to write and easy to get wrong.

1. Demo identity seeding must be impossible in production.
2. Role-name comparisons must fail the build.

Both are tested against their own failure mode, because a guard that has never
been seen to refuse anything is a guard nobody has tested.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from fitos_api.settings import Environment, Settings
from pydantic import ValidationError

CHECKER = Path(__file__).resolve().parents[1] / "tools" / "check_no_role_comparisons.py"


class TestDemoAuthProductionGuard:
    def test_demo_auth_in_production_refuses_to_construct(self) -> None:
        """The process must fail at startup, not serve with a bypass open."""
        with pytest.raises(ValidationError) as exc:
            Settings(environment=Environment.PRODUCTION, demo_auth_enabled=True)
        assert "must not be true" in str(exc.value)

    @pytest.mark.parametrize(
        "environment",
        [Environment.LOCAL, Environment.PREVIEW, Environment.STAGING],
    )
    def test_demo_auth_is_allowed_outside_production(self, environment: Environment) -> None:
        settings = Settings(environment=environment, demo_auth_enabled=True)
        assert settings.demo_auth_enabled is True

    def test_production_without_demo_auth_is_fine(self) -> None:
        settings = Settings(environment=Environment.PRODUCTION, demo_auth_enabled=False)
        assert settings.is_production is True

    def test_the_default_is_off(self) -> None:
        """A forgotten setting must default to the safe value."""
        assert Settings().demo_auth_enabled is False


class TestRoleComparisonChecker:
    def _run(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CHECKER), str(root)],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_it_flags_an_equality_comparison(self, tmp_path: Path) -> None:
        (tmp_path / "handler.py").write_text(
            textwrap.dedent(
                """
                def allowed(principal):
                    return principal.role == "manager"
                """
            )
        )
        result = self._run(tmp_path)
        assert result.returncode == 1
        assert "compares a role against" in result.stderr

    def test_it_flags_a_prefix_match(self, tmp_path: Path) -> None:
        (tmp_path / "handler.py").write_text(
            textwrap.dedent(
                """
                def allowed(user_role):
                    return user_role.startswith("admin")
                """
            )
        )
        assert self._run(tmp_path).returncode == 1

    def test_it_does_not_flag_a_capability_check(self, tmp_path: Path) -> None:
        (tmp_path / "handler.py").write_text(
            textwrap.dedent(
                """
                def allowed(principal):
                    return principal.can(Capability.GAP_ASSIGN)
                """
            )
        )
        assert self._run(tmp_path).returncode == 0

    def test_it_does_not_flag_prose_mentioning_a_role(self, tmp_path: Path) -> None:
        """The rule is explained in comments and docstrings all over this
        repository. A checker that trips on its own documentation gets turned
        off, so it must not."""
        (tmp_path / "handler.py").write_text(
            textwrap.dedent(
                '''
                """Never write role == "manager"; use a capability instead."""

                # Historically this compared role == "admin".
                ROLE_DOCS = "manager"

                def allowed(principal):
                    return principal.can(Capability.MEMBER_MANAGE)
                '''
            )
        )
        result = self._run(tmp_path)
        assert result.returncode == 0, result.stderr

    def test_the_real_source_tree_is_clean(self) -> None:
        """The rule holds for the code as it actually stands."""
        root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            [sys.executable, str(CHECKER), str(root / "services")],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
