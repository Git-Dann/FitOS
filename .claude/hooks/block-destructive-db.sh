#!/usr/bin/env bash
# PreToolUse hook for Bash.
# Blocks destructive database and data commands outside the sanctioned demo path.
# See CLAUDE.md "Destructive commands" and .claude/skills/run-demo-reset/SKILL.md.
set -uo pipefail

payload="$(cat)"
cmd="$(printf '%s' "$payload" | jq -r '.tool_input.command // empty')"
[ -z "$cmd" ] && exit 0

deny() {
  echo "BLOCKED: $1" >&2
  echo "The only sanctioned data-destructive path is: pnpm demo:seed | demo:reset | demo:snapshot | demo:purge | demo:verify" >&2
  echo "Run with --dry-run first. See .claude/skills/run-demo-reset/SKILL.md." >&2
  exit 2
}

lower="$(printf '%s' "$cmd" | tr '[:upper:]' '[:lower:]')"

# Sanctioned demo commands pass through.
case "$lower" in
  *demo:seed*|*demo:reset*|*demo:snapshot*|*demo:purge*|*demo:verify*) exit 0 ;;
esac

# SQL destructive statements.
case "$lower" in
  *"drop database"*|*"drop schema"*|*"drop table"*)
    deny "SQL DROP against a database, schema or table." ;;
  *"truncate table"*|*"truncate only "*)
    deny "SQL TRUNCATE." ;;
esac

# DELETE / UPDATE with no WHERE clause.
if printf '%s' "$lower" | grep -Eq 'delete[[:space:]]+from[[:space:]]+[a-z0-9_."]+[[:space:]]*(;|$)'; then
  deny "DELETE FROM with no WHERE clause."
fi
if printf '%s' "$lower" | grep -Eq 'update[[:space:]]+[a-z0-9_."]+[[:space:]]+set[[:space:]]' \
   && ! printf '%s' "$lower" | grep -q 'where'; then
  deny "UPDATE with no WHERE clause."
fi

# Tool-level destruction.
case "$lower" in
  *dropdb*)                      deny "dropdb." ;;
  *"alembic downgrade base"*)    deny "alembic downgrade to base." ;;
  *"prisma migrate reset"*|*"drizzle-kit drop"*) deny "an ORM reset/drop command." ;;
  *"docker compose down -v"*|*"docker-compose down -v"*)
    deny "docker compose down -v, which deletes local data volumes." ;;
  *"docker volume rm"*|*"docker volume prune"*)
    deny "removal of docker volumes holding local database state." ;;
esac

# Reckless filesystem deletion.
if printf '%s' "$lower" | grep -Eq 'rm[[:space:]]+(-[a-z]*[rf][a-z]*[[:space:]]+)+(/|~|\$home)([[:space:]]|$)'; then
  deny "recursive delete of a root or home path."
fi

exit 0
