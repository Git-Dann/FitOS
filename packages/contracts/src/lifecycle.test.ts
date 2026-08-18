/**
 * The TypeScript half of the lifecycle contract.
 *
 * The Python half has its own tests and a drift check on the artefact. What is
 * left to prove here is that this module reads that artefact correctly — a
 * generated table consumed by a buggy reader is no better than a hand-copied
 * one.
 */
import assert from "node:assert/strict";
import test from "node:test";
import {
  DISMISSAL_REASONS,
  GAP_STATUSES,
  capabilityFor,
  checkTransition,
  isTerminal,
  legalTransitions,
} from "./lifecycle.ts";

const ALL: readonly string[] = ["gap.transition", "gap.dismiss"];

test("the contract is loaded, not empty", () => {
  // A reader that silently got `{}` would make every check below vacuous.
  assert.equal(GAP_STATUSES.length, 7);
  assert.ok(DISMISSAL_REASONS.length >= 5);
});

test("terminal statuses reach nothing", () => {
  assert.deepEqual(legalTransitions("resolved"), []);
  assert.deepEqual(legalTransitions("dismissed"), []);
  assert.ok(isTerminal("resolved"));
  assert.ok(isTerminal("dismissed"));
  assert.ok(!isTerminal("detected"));
});

test("the forward chain matches the module", () => {
  assert.deepEqual(legalTransitions("detected").sort(), ["dismissed", "triaged"]);
  assert.deepEqual(legalTransitions("validating").sort(), ["dismissed", "resolved"]);
});

test("there is no backward edge", () => {
  const order = ["detected", "triaged", "investigating", "actioned", "validating"] as const;
  order.forEach((source, index) => {
    order.slice(0, index).forEach((earlier) => {
      assert.ok(
        !legalTransitions(source).includes(earlier),
        `${source} must not reach back to ${earlier}`,
      );
    });
  });
});

test("dismissal needs its own capability", () => {
  assert.equal(capabilityFor("dismissed"), "gap.dismiss");
  assert.equal(capabilityFor("triaged"), "gap.transition");
});

test("a caller with gap.transition alone cannot dismiss", () => {
  // The discriminating case: a caller holding neither capability is refused
  // either way and cannot tell the two apart.
  const refusal = checkTransition({
    from: "detected",
    to: "dismissed",
    capabilities: ["gap.transition"],
    reasonCode: "duplicate",
    note: "Already tracked.",
    hasOwner: true,
  });
  assert.equal(refusal?.reason, "not_permitted");

  const allowed = checkTransition({
    from: "detected",
    to: "triaged",
    capabilities: ["gap.transition"],
    hasOwner: true,
  });
  assert.equal(allowed, null);
});

test("a terminal gap refuses every transition, and says so", () => {
  const refusal = checkTransition({
    from: "dismissed",
    to: "triaged",
    capabilities: ALL,
    hasOwner: true,
  });
  assert.equal(refusal?.reason, "terminal");
  assert.match(refusal!.message, /terminal/);
});

test("an illegal transition is distinguished from a terminal one", () => {
  const refusal = checkTransition({
    from: "detected",
    to: "resolved",
    capabilities: ALL,
    hasOwner: true,
    outcomeId: "o1",
  });
  assert.equal(refusal?.reason, "illegal");
});

test("dismissal needs a reason code and a note", () => {
  const noCode = checkTransition({
    from: "detected",
    to: "dismissed",
    capabilities: ALL,
    note: "n",
    hasOwner: true,
  });
  assert.equal(noCode?.reason, "missing_requirement");

  const noNote = checkTransition({
    from: "detected",
    to: "dismissed",
    capabilities: ALL,
    reasonCode: "duplicate",
    hasOwner: true,
  });
  assert.match(noNote!.message, /note/);

  const blankNote = checkTransition({
    from: "detected",
    to: "dismissed",
    capabilities: ALL,
    reasonCode: "duplicate",
    note: "   ",
    hasOwner: true,
  });
  assert.equal(blankNote?.reason, "missing_requirement");

  const complete = checkTransition({
    from: "detected",
    to: "dismissed",
    capabilities: ALL,
    reasonCode: "duplicate",
    note: "Already tracked under an earlier gap.",
    hasOwner: true,
  });
  assert.equal(complete, null);
});

test("an unknown dismissal reason is refused", () => {
  const refusal = checkTransition({
    from: "detected",
    to: "dismissed",
    capabilities: ALL,
    reasonCode: "because_i_said_so",
    note: "n",
    hasOwner: true,
  });
  assert.equal(refusal?.reason, "missing_requirement");
});

test("resolution needs an outcome", () => {
  const refusal = checkTransition({
    from: "validating",
    to: "resolved",
    capabilities: ALL,
    hasOwner: true,
  });
  assert.match(refusal!.message, /outcome/);

  const complete = checkTransition({
    from: "validating",
    to: "resolved",
    capabilities: ALL,
    outcomeId: "outcome-1",
    hasOwner: true,
  });
  assert.equal(complete, null);
});

test("triage needs an owner", () => {
  const refusal = checkTransition({
    from: "detected",
    to: "triaged",
    capabilities: ALL,
    hasOwner: false,
  });
  assert.match(refusal!.message, /owner/);
});

test("permission is checked before legality", () => {
  // So a caller who may not act on gaps at all learns that, rather than
  // learning the shape of the workflow from a legality error.
  const refusal = checkTransition({
    from: "dismissed",
    to: "triaged",
    capabilities: [],
    hasOwner: true,
  });
  assert.equal(refusal?.reason, "not_permitted");
});
