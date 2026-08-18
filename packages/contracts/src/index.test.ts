import assert from "node:assert/strict";
import test from "node:test";
import { isReady, type ReadyStatus } from "./index.ts";

const base = (status: ReadyStatus["status"]): ReadyStatus => ({
  status,
  service: "api",
  checks: { postgres: { ok: status === "ready" } },
});

test("isReady is true only for a fully ready service", () => {
  assert.equal(isReady(base("ready")), true);
  assert.equal(isReady(base("degraded")), false);
});

test("a degraded check carries a detail and never a secret", () => {
  const r: ReadyStatus = {
    status: "degraded",
    service: "api",
    checks: { postgres: { ok: false, detail: "connection refused" } },
  };
  assert.equal(isReady(r), false);
  assert.match(r.checks.postgres!.detail!, /connection refused/);
  assert.doesNotMatch(JSON.stringify(r), /password|secret|token/i);
});
