#!/usr/bin/env bash
# Local infrastructure lifecycle. `pnpm dev:infra` brings everything up and
# waits for health; `pnpm dev:infra:down` stops it.
#
# Deliberately does NOT support `down -v`. Deleting local data volumes is a
# destructive action and the only sanctioned destructive path is the demo
# command set (CLAUDE.md, "Destructive commands"). Remove a volume by hand if
# you genuinely mean to.
set -euo pipefail

COMPOSE_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../compose" && pwd)/docker-compose.yml"

if ! docker compose version >/dev/null 2>&1; then
  echo "error: 'docker compose' is unavailable. Install Docker Desktop or the compose plugin." >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "error: the Docker daemon is not running." >&2
  exit 1
fi

case "${1:-up}" in
  up)
    echo "starting FitOS local infrastructure…"
    docker compose -f "$COMPOSE_FILE" up -d --wait --wait-timeout 300
    echo
    docker compose -f "$COMPOSE_FILE" ps --format 'table {{.Service}}\t{{.Status}}'
    cat <<'EOM'

ready:
  postgres     localhost:5432   fitos / fitos_local_only
  clickhouse   localhost:8123   fitos / fitos_local_only
  minio        localhost:9002   console http://localhost:9001
  temporal     localhost:7233   ui      http://localhost:8233
  cube         localhost:4000

These credentials are local-only placeholders and are not secrets. Real
credentials come from the secret manager and are never committed.

next: pnpm dev
EOM
    ;;
  down)
    docker compose -f "$COMPOSE_FILE" down
    echo "stopped. Data volumes are preserved."
    ;;
  status)
    docker compose -f "$COMPOSE_FILE" ps
    ;;
  footprint)
    # Phase A acceptance: record the local resource cost before the ~1.4M
    # record demo dataset exists (docs/spec-review.md T1).
    docker compose -f "$COMPOSE_FILE" ps -q \
      | xargs -r docker stats --no-stream \
          --format 'table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}'
    ;;
  *)
    echo "usage: dev-infra.sh [up|down|status|footprint]" >&2
    exit 2
    ;;
esac
