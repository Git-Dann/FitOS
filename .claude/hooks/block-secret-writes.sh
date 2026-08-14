#!/usr/bin/env bash
# PreToolUse hook for Write|Edit|NotebookEdit.
# Blocks writes to real environment and secret files.
# Exit 2 = block the tool call and show stderr to Claude.
set -uo pipefail

payload="$(cat)"
path="$(printf '%s' "$payload" | jq -r '.tool_input.file_path // empty')"
[ -z "$path" ] && exit 0

base="$(basename "$path")"

# Templates and examples are safe to edit; real secret files are not.
case "$base" in
  .env.example|.env.template|.env.sample) exit 0 ;;
esac

case "$base" in
  .env|.env.*|*.pem|*.key|*.p12|*.pfx|id_rsa|id_ed25519|credentials|.npmrc|.pypirc)
    echo "BLOCKED: '$path' looks like a real secret or environment file." >&2
    echo "Secrets belong in a secret manager. Edit .env.example instead, and document the variable in docs/local-development.md." >&2
    exit 2
    ;;
esac

case "$path" in
  */secrets/*|*/.secrets/*|*/.aws/*|*/.ssh/*)
    echo "BLOCKED: '$path' is inside a secrets directory." >&2
    exit 2
    ;;
esac

exit 0
