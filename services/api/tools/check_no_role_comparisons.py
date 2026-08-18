#!/usr/bin/env python3
"""Fail the build on a role-name comparison in application code.

CLAUDE.md: "Capabilities, not roles. `can("gap.assign")`, never
`role == "manager"`." A rule nobody can enforce is a suggestion, so this makes
it mechanical.

AST-based rather than grep: a grep for `role ==` also matches the string inside
a docstring, a comment explaining the rule, and the test that asserts the rule
works — and a checker that cries wolf gets disabled.

What is flagged: comparing anything whose name ends in `role` (or a `.role`
attribute) against a string literal that names one of the six roles.

What is not:

- the capability layer itself, which necessarily maps roles to capabilities;
- test code, which legitimately asserts on a stored role value ("this
  cross-tenant PATCH did not change the target's role"). The rule is about
  authorisation decisions, and authorisation does not happen in tests. This
  exemption is deliberate and narrow: it covers `tests/` directories only.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROLE_NAMES = frozenset({"frontline", "manager", "analyst", "admin", "owner", "presenter-demo"})

# The role-to-capability map is the one place role names legitimately appear.
EXEMPT = (
    "capabilities.py",
    "check_no_role_comparisons.py",
)


def _is_role_ref(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id.lower().endswith("role")
    if isinstance(node, ast.Attribute):
        return node.attr.lower().endswith("role")
    return False


def _is_role_literal(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in ROLE_NAMES
    )


class RoleComparisonVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.findings: list[tuple[int, str]] = []

    def visit_Compare(self, node: ast.Compare) -> None:
        operands = [node.left, *node.comparators]
        has_role_ref = any(_is_role_ref(o) for o in operands)
        role_literals = [o for o in operands if _is_role_literal(o)]
        if has_role_ref and role_literals:
            literal = role_literals[0]
            name = literal.value if isinstance(literal, ast.Constant) else "?"
            self.findings.append((node.lineno, f'compares a role against "{name!s}"'))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # role in ("manager", "admin") reads differently but is the same defect.
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in {"startswith", "endswith"}
            and _is_role_ref(node.func.value)
            and any(_is_role_literal(a) for a in node.args)
        ):
            self.findings.append((node.lineno, "matches a role name by prefix or suffix"))
        self.generic_visit(node)


def check_file(path: Path) -> list[str]:
    if path.name in EXEMPT:
        return []
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError as exc:
        return [f"{path}:{exc.lineno}: could not parse: {exc.msg}"]

    visitor = RoleComparisonVisitor(path)
    visitor.visit(tree)
    return [f"{path}:{line}: {message}" for line, message in visitor.findings]


def main(roots: list[str]) -> int:
    findings: list[str] = []
    for root in roots:
        for path in Path(root).rglob("*.py"):
            parts = set(path.parts)
            if parts & {".venv", "__pycache__", "node_modules"}:
                continue
            if "tests" in parts:  # see module docstring
                continue
            findings.extend(check_file(path))

    if findings:
        print("Role-name comparisons found. Use a capability instead:\n", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        print(
            '\n  can("gap.assign") — not role == "manager".'
            "\n  See CLAUDE.md and services/api/src/fitos_api/capabilities.py.",
            file=sys.stderr,
        )
        return 1

    print(f"no role-name comparisons in {', '.join(roots)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or ["services", "connectors"]))
