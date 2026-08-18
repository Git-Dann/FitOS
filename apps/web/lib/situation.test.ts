/**
 * Tests for the orientation summary.
 *
 * The summary is the one place in the product that *adds money up*, so these
 * tests exist to prove it refuses in every case where adding would be a lie.
 * Each case is built to discriminate: a fixture where every gap is withheld
 * cannot tell "some are withheld" from "all are", and a currency test where
 * the two figures differ cannot tell "refused to add" from "added wrongly".
 */
import assert from "node:assert/strict";
import test from "node:test";
import { STALE_SECONDS, summarise } from "./situation";
import type { DemoGap } from "./demo-gaps";

/** A minimally-populated gap. Only the fields the summary reads are real. */
function gap(overrides: Partial<DemoGap> = {}): DemoGap {
  return {
    id: "id",
    reference: "NS-001",
    packKey: "retail_omnichannel",
    gapType: "stock_truth_mismatch",
    gapTypeLabel: "Stock truth",
    title: "t",
    summary: "s",
    scopeType: "location",
    scopeId: "Somewhere",
    metricKey: "m",
    metricVersion: 1,
    observedValue: 1,
    expectedValue: 0,
    unit: "count",
    observedLabel: "1",
    expectedLabel: "0",
    exposureLow: 100,
    exposureBase: 200,
    exposureHigh: 400,
    currency: "GBP",
    isModelled: false,
    formulaLabel: null,
    assumptions: [],
    confidenceScore: 0.9,
    confidenceBand: "high",
    confidenceComponents: [],
    confidenceDropped: [],
    severity: "high",
    status: "detected",
    ownerInitials: "DA",
    firstSeenAt: "2026-08-01T00:00:00Z",
    lastSeenAt: "2026-08-18T00:00:00Z",
    asOfAt: "2026-08-18T14:00:00Z",
    dataFreshnessSeconds: 60,
    ruleKey: "r",
    ruleVersion: 1,
    reasonCodes: [],
    evidence: [],
    recommendedActions: [],
    ...overrides,
  };
}

test("the envelope sums low to low and high to high, and never touches base", () => {
  const summary = summarise([
    gap({ exposureLow: 100, exposureBase: 200, exposureHigh: 400 }),
    gap({ exposureLow: 50, exposureBase: 90, exposureHigh: 150 }),
  ]);
  assert.equal(summary.exposure.kind, "range");
  if (summary.exposure.kind !== "range") return;
  assert.equal(summary.exposure.low, 150);
  assert.equal(summary.exposure.high, 550);
  // The sum of bases is 290. If it ever appears, a precise figure standing on
  // modelled inputs has reached a surface, which is what §3 forbids.
  assert.equal(Object.values(summary.exposure).includes(290), false);
  assert.equal("base" in summary.exposure, false);
});

test("a low-confidence gap is excluded from the envelope and counted", () => {
  // Discriminating: the excluded gap's figures are an order of magnitude larger
  // than the included one, so folding it in could not be mistaken for excluding it.
  const summary = summarise([
    gap({ exposureLow: 100, exposureHigh: 400, confidenceBand: "high" }),
    gap({ exposureLow: 9_000, exposureHigh: 90_000, confidenceBand: "low" }),
  ]);
  assert.equal(summary.exposure.kind, "range");
  if (summary.exposure.kind !== "range") return;
  assert.equal(summary.exposure.low, 100);
  assert.equal(summary.exposure.high, 400);
  assert.equal(summary.exposure.excludedLowConfidence, 1);
  assert.equal(summary.exposure.contributing, 1);
});

test("one withheld gap withholds the whole envelope", () => {
  // The discriminating input: one priced gap and one withheld. A fixture where
  // everything is withheld would pass even if the rule were "withhold only when
  // nothing is priced", which is the opposite rule.
  const withheld = gap();
  delete withheld.exposureLow;
  delete withheld.exposureBase;
  delete withheld.exposureHigh;
  delete withheld.currency;

  const summary = summarise([gap({ exposureLow: 100, exposureHigh: 400 }), withheld]);
  assert.equal(summary.exposure.kind, "withheld");
});

test("an absent exposure field and a null one are different answers", () => {
  // null means "this kind of gap carries no money" — a complete answer.
  const summary = summarise([
    gap({ exposureLow: null, exposureBase: null, exposureHigh: null, currency: null }),
  ]);
  assert.equal(summary.exposure.kind, "none");
});

test("two currencies are not added", () => {
  // Identical figures on purpose: if the envelope summed them it would return a
  // perfectly plausible range, and only the currency tells you it is nonsense.
  const summary = summarise([
    gap({ exposureLow: 100, exposureHigh: 400, currency: "GBP" }),
    gap({ exposureLow: 100, exposureHigh: 400, currency: "EUR" }),
  ]);
  assert.equal(summary.exposure.kind, "mixed");
  if (summary.exposure.kind !== "mixed") return;
  assert.deepEqual(summary.exposure.currencies, ["EUR", "GBP"]);
});

test("the envelope carries the weakest band it contains", () => {
  const summary = summarise([gap({ confidenceBand: "high" }), gap({ confidenceBand: "medium" })]);
  assert.equal(summary.exposure.kind, "range");
  if (summary.exposure.kind !== "range") return;
  assert.equal(summary.exposure.band, "medium");
});

test("one modelled input makes the whole envelope modelled", () => {
  const summary = summarise([gap({ isModelled: false }), gap({ isModelled: true })]);
  assert.equal(summary.exposure.kind, "range");
  if (summary.exposure.kind !== "range") return;
  assert.equal(summary.exposure.isModelled, true);
});

test("unpriced gaps are counted beside the envelope, not inside it", () => {
  const summary = summarise([
    gap({ exposureLow: 100, exposureHigh: 400 }),
    gap({ exposureLow: null, exposureBase: null, exposureHigh: null, currency: null }),
  ]);
  assert.equal(summary.exposure.kind, "range");
  if (summary.exposure.kind !== "range") return;
  assert.equal(summary.exposure.withoutExposure, 1);
  assert.equal(summary.exposure.contributing, 1);
});

test("staleness is a strict threshold and unknown age is its own count", () => {
  const summary = summarise([
    gap({ dataFreshnessSeconds: STALE_SECONDS }),
    gap({ dataFreshnessSeconds: STALE_SECONDS + 1 }),
    gap({ dataFreshnessSeconds: null }),
  ]);
  // Exactly at the threshold is not yet stale; one second past it is.
  assert.equal(summary.stale, 1);
  // Unknown age is never silently rolled into the stale count — the strip says
  // both, because "we do not know" and "we know it is old" are different.
  assert.equal(summary.ageUnknown, 1);
});

test("severity counts keep the ranked order and drop empty bands", () => {
  const summary = summarise([
    gap({ severity: "medium" }),
    gap({ severity: "critical" }),
    gap({ severity: "medium" }),
  ]);
  assert.deepEqual(summary.bySeverity, [
    { severity: "critical", count: 1 },
    { severity: "medium", count: 2 },
  ]);
  assert.equal(summary.total, 3);
  assert.equal(summary.unowned, 0);
});

test("an empty ledger summarises to nothing rather than to zero money", () => {
  const summary = summarise([]);
  assert.equal(summary.total, 0);
  assert.deepEqual(summary.bySeverity, []);
  // Not a £0 envelope. Zero exposure is a claim; no gaps is an absence.
  assert.equal(summary.exposure.kind, "none");
});
