/**
 * Contract tests over the radar fixture.
 *
 * Concept B's documented risks are the specification here. Two of them are
 * checkable, and both describe a failure that looks completely normal on screen:
 *
 *   "Naturally surfaces data-quality holes as visible gaps in the grid rather
 *    than as an absence of rows."
 *
 * A grid where every cell has a reading cannot demonstrate that, and a fixture
 * with no `null` in it would let the no-reading treatment rot untested — it
 * would still compile, still render, and simply never appear.
 *
 *   "There is no obvious home for confidence or exposure ranges."
 *
 * The grid's answer is that it carries neither, so nothing here may express a
 * quantity at all. A cell is a band, and the bands are a closed set.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { CHANNELS, RADAR_HOURS, RADAR_ROWS, pressureTotals } from "./demo-radar";
import { DEMO_GAPS } from "./demo-gaps";

test("the fixture is populated", () => {
  assert.ok(RADAR_ROWS.length >= 8, `${RADAR_ROWS.length} rows`);
  assert.ok(CHANNELS.length >= 5, `${CHANNELS.length} channels`);
});

test("every row has exactly one cell per hour", () => {
  // A short row silently shifts every later cell into the wrong hour, and the
  // grid still draws — it just describes a different afternoon.
  for (const row of RADAR_ROWS) {
    assert.equal(
      row.cells.length,
      RADAR_HOURS.length,
      `${row.reference} has ${row.cells.length} cells for ${RADAR_HOURS.length} hours`,
    );
  }
});

test("every row belongs to a gap that exists", () => {
  // A cell links to its gap for the evidence. A row whose reference matches no
  // gap renders as an unclickable cell, which is the pattern-without-evidence
  // failure Concept B warns about, arrived at by accident.
  const references = new Set(DEMO_GAPS.map((gap) => gap.reference));
  for (const row of RADAR_ROWS) {
    assert.ok(references.has(row.reference), `${row.reference} matches no gap`);
  }
});

test("the grid agrees with the ledger about scope", () => {
  // A dashboard that disagrees with the list it links to is worse than no
  // dashboard: both look authoritative and only one can be right.
  const scopeByReference = new Map(DEMO_GAPS.map((gap) => [gap.reference, gap.scopeId]));
  for (const row of RADAR_ROWS) {
    assert.equal(
      row.scopeId,
      scopeByReference.get(row.reference),
      `${row.reference} scope differs`,
    );
  }
});

test("the no-reading state is actually exercised", () => {
  // The whole reason a heat grid earns its place here. A fixture in which every
  // hour reported cannot detect a build that renders `null` as "normal".
  const totals = pressureTotals(RADAR_ROWS);
  assert.ok(totals.unknown > 0, "no cell is missing a reading, so the state is untested");
  // And a row that is entirely unknown, which is the stopped-counter case.
  const allUnknown = RADAR_ROWS.filter((row) => row.cells.every((cell) => cell === null));
  assert.ok(allUnknown.length > 0, "no row is entirely unknown");
  // And a partial row, which is the different and easier-to-miss case.
  const partial = RADAR_ROWS.filter(
    (row) => row.cells.some((cell) => cell === null) && row.cells.some((cell) => cell !== null),
  );
  assert.ok(partial.length > 0, "no row is partially unknown");
});

test("every band in the grid is one of the four documented states", () => {
  // A cell may not express a quantity. If a number ever reaches this fixture,
  // the grid has started making the claim Concept B says it must not.
  const allowed = new Set(["normal", "elevated", "pressure", null]);
  for (const row of RADAR_ROWS) {
    for (const cell of row.cells) {
      assert.ok(allowed.has(cell), `${row.reference} carries ${JSON.stringify(cell)}`);
    }
  }
});

test("the totals account for every cell exactly once", () => {
  const totals = pressureTotals(RADAR_ROWS);
  const counted = totals.normal + totals.elevated + totals.pressure + totals.unknown;
  assert.equal(counted, RADAR_ROWS.length * RADAR_HOURS.length);
});

test("a channel reading a broken source has no series and no comparison", () => {
  // A flat sparkline over a stale denominator is the most convincing kind of
  // lie: it looks like stability. And `null` delta must never become "flat".
  for (const channel of CHANNELS) {
    if (!channel.unreliable) continue;
    const drawable = channel.series.length >= 2;
    assert.ok(
      !drawable || channel.delta === null,
      `${channel.key} draws a line and claims a comparison over an unreliable source`,
    );
  }
  // At least one channel must exercise the state, or the treatment is untested.
  assert.ok(
    CHANNELS.some((channel) => channel.unreliable),
    "no channel exercises the unreliable-source state",
  );
  assert.ok(
    CHANNELS.some((channel) => channel.series.length === 0),
    "no channel exercises the no-series state",
  );
});

test("every channel cites a governed metric", () => {
  // The strip cites rather than asserts. A reading with no metric key is a
  // number the reader cannot trace, which is what this product exists to end.
  for (const channel of CHANNELS) {
    assert.match(channel.metricKey, /^[a-z][a-z0-9_]+$/, `${channel.key}: ${channel.metricKey}`);
    assert.ok(channel.reading.length > 0, `${channel.key} has no reading`);
  }
});

test("channel gap counts do not exceed the open gaps that exist", () => {
  const open = DEMO_GAPS.filter(
    (gap) => gap.status !== "resolved" && gap.status !== "dismissed",
  ).length;
  const claimed = CHANNELS.reduce((sum, channel) => sum + channel.gapCount, 0);
  assert.ok(claimed <= open, `channels claim ${claimed} gaps but only ${open} are open`);
});
