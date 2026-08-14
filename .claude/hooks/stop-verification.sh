#!/usr/bin/env bash
# Stop hook. Reminds that completion claims need executed evidence.
# Advisory by design: it reports, it does not block, because "the turn ended"
# is not the same event as "a phase was claimed complete".
set -uo pipefail

cd "$(dirname "$0")/../.." || exit 0

msg=""

# Uncommitted work is worth surfacing at the end of a turn.
if command -v git >/dev/null 2>&1 && git rev-parse --git-dir >/dev/null 2>&1; then
  dirty="$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
  [ "$dirty" != "0" ] && msg="${msg}${dirty} uncommitted change(s) in the working tree. "
fi

# Once the monorepo exists, point at the real gate.
if [ -f pnpm-workspace.yaml ]; then
  msg="${msg}Before claiming a phase complete: run 'pnpm verify', quote the output, and update docs/build-state.md."
else
  msg="${msg}Pre-monorepo: 'npm test' is known broken (see docs/repo-audit.md). Use 'npm run build:vinext && node --test tests/rendered-html.test.mjs'."
fi

[ -n "$msg" ] && echo "$msg" >&2
exit 0
