/**
 * Contract tests over the demonstration fixture.
 *
 * The fixture is shaped like the aggregate rather than like the screen, which
 * is only worth doing if it also *obeys* the aggregate's rules. These are the
 * rules from docs/gap-model.md that a hand-written fixture can violate silently
 * — and one of them was being violated: a modelled exposure with low, base and
 * high all set to the same number, which renders as a single exact figure
 * standing on an assumption.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { DEMO_GAPS, hasExposure } from "./demo-gaps";

test("the fixture is populated", () => {
  // Every assertion below is vacuous over an empty array.
  assert.ok(DEMO_GAPS.length >= 8, `expected >= 8 gaps, got ${DEMO_GAPS.length}`);
});

test("a modelled exposure is never a point estimate", () => {
  // §3: "never present a single precise financial value when the inputs do not
  // support that precision". An observed exposure may legitimately be exact; a
  // modelled one may not, because at least one of its inputs is a band.
  const collapsed = DEMO_GAPS.filter(
    (gap) => gap.isModelled && hasExposure(gap) && gap.exposureLow === gap.exposureHigh,
  ).map((gap) => gap.reference);
  assert.deepEqual(collapsed, [], `modelled gaps with a zero-width interval: ${collapsed}`);
});

test("every exposure is ordered low <= base <= high", () => {
  for (const gap of DEMO_GAPS) {
    if (!hasExposure(gap)) continue;
    assert.ok(typeof gap.exposureBase === "number", `${gap.reference}: priced but carries no base`);
    assert.ok(
      gap.exposureLow <= (gap.exposureBase as number) &&
        (gap.exposureBase as number) <= gap.exposureHigh,
      `${gap.reference}: ${gap.exposureLow}/${gap.exposureBase}/${gap.exposureHigh} out of order`,
    );
  }
});

test("a wide interval forces the low confidence band and its reason code", () => {
  // §3: "high / low ratio above a pack-configured limit (default 5x) forces
  // confidence_band = low and adds reason code wide_exposure_interval".
  for (const gap of DEMO_GAPS) {
    if (!hasExposure(gap) || gap.exposureLow === 0) continue;
    if (gap.exposureHigh / gap.exposureLow <= 5) continue;
    assert.equal(gap.confidenceBand, "low", `${gap.reference}: wide interval, band not low`);
    assert.ok(
      gap.reasonCodes.includes("wide_exposure_interval"),
      `${gap.reference}: wide interval without its reason code`,
    );
  }
});

test("a modelled exposure names at least one assumption", () => {
  // §3: "no modelled money without low, base, high, assumptions and
  // confidence". An unexplained model is not auditable.
  for (const gap of DEMO_GAPS) {
    if (!gap.isModelled) continue;
    assert.ok(gap.formulaLabel, `${gap.reference}: modelled with no formula label`);
    assert.ok(
      gap.assumptions.some((assumption) => assumption.kind === "assumption"),
      `${gap.reference}: modelled but every input is observed`,
    );
    assert.ok(
      gap.reasonCodes.includes("modelled_exposure"),
      `${gap.reference}: modelled without the modelled_exposure reason code`,
    );
  }
});

test("every gap carries the four things a gap may not exist without", () => {
  // CLAUDE.md: "no gap without a metric version, detector version, evidence and
  // an as-of time".
  for (const gap of DEMO_GAPS) {
    assert.ok(gap.metricVersion >= 1, `${gap.reference}: no metric version`);
    assert.ok(gap.ruleVersion >= 1, `${gap.reference}: no detector version`);
    assert.ok(gap.evidence.length > 0, `${gap.reference}: no evidence`);
    assert.ok(!Number.isNaN(Date.parse(gap.asOfAt)), `${gap.reference}: no as-of time`);
  }
});

test("every gap offers at least one next step", () => {
  // The row surfaces `recommendedActions[0]` as its answer to "so what". A gap
  // with an empty array renders a row that states a problem and stops.
  for (const gap of DEMO_GAPS) {
    assert.ok(gap.recommendedActions.length > 0, `${gap.reference}: no recommended action`);
    for (const action of gap.recommendedActions) {
      assert.ok(
        action.title && action.rationale && action.playbookId,
        `${gap.reference}: thin action`,
      );
      // Packs own their vocabulary: a playbook id is pack-scoped, not bare.
      assert.match(
        action.playbookId,
        /^[a-z]+\.[a-z_]+\.v\d+$/,
        `${gap.reference}: ${action.playbookId}`,
      );
    }
  }
});
