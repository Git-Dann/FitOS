#!/usr/bin/env bash
# Build, then serve the standalone output on a known port, refusing to hand back
# a stale server. `next start` does not work with `output: standalone`, and the
# failure mode is a server that answers 200 while 500ing its own assets — which
# is how two earlier rounds of this build got reviewed against the wrong bits.
set -euo pipefail
PORT="${1:-3112}"
cd "$(dirname "$0")/.."

fuser -k "${PORT}/tcp" 2>/dev/null || true
sleep 1

pnpm exec next build >/tmp/fitos-build.log 2>&1 || { tail -20 /tmp/fitos-build.log; exit 1; }
cp -r .next/static .next/standalone/apps/web/.next/
[ -d public ] && cp -r public .next/standalone/apps/web/ || true

PORT="$PORT" node .next/standalone/apps/web/server.js >/tmp/fitos-serve.log 2>&1 &
echo $! > /tmp/fitos-serve.pid

for _ in $(seq 1 40); do
  if curl -sf -o /dev/null "http://localhost:${PORT}/"; then
    echo "serving build $(cat .next/BUILD_ID) on ${PORT} (pid $(cat /tmp/fitos-serve.pid))"
    exit 0
  fi
  sleep 0.5
done
echo "server never became ready" >&2
tail -20 /tmp/fitos-serve.log >&2
exit 1
