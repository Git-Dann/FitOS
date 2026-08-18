#!/usr/bin/env bash
# PostToolUse hook for Write|Edit.
# Formats the touched file and runs a targeted check. Fast and scoped by design —
# the full suite runs in CI and via `pnpm verify`.
# Never blocks: formatting problems are reported, not enforced here.
set -uo pipefail

payload="$(cat)"
path="$(printf '%s' "$payload" | jq -r '.tool_input.file_path // empty')"
[ -z "$path" ] || [ ! -f "$path" ] && exit 0

cd "$(dirname "$0")/../.." || exit 0

case "$path" in
  */legacy/*|*/node_modules/*|*/.next/*|*/dist/*) exit 0 ;;
esac

case "$path" in
  *.ts|*.tsx|*.js|*.jsx|*.mjs|*.cjs|*.json|*.css|*.md)
    if [ -x node_modules/.bin/prettier ]; then
      node_modules/.bin/prettier --write --log-level warn "$path" 2>/dev/null || true
    fi
    ;;
  *.py)
    if command -v ruff >/dev/null 2>&1; then
      ruff format "$path" >/dev/null 2>&1 || true
      ruff check --fix "$path" 2>&1 | head -20 || true
    fi
    ;;
esac

# Targeted type check for TypeScript. Project-wide because tsc has no reliable
# single-file mode with path aliases; kept quiet and non-blocking.
case "$path" in
  *.ts|*.tsx)
    if [ -x node_modules/.bin/tsc ]; then
      out="$(node_modules/.bin/tsc --noEmit 2>&1 | head -20)"
      [ -n "$out" ] && printf 'Type errors after editing %s:\n%s\n' "$path" "$out" >&2
    fi
    ;;
esac

exit 0
