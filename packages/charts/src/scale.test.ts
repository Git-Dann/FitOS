/**
 * Tests for the scale maths.
 *
 * These exist because a wrong scale is invisible. A bar drawn at 61% of its
 * track when it should be at 67% looks exactly like a bar — nothing about the
 * picture says the mapping is broken, and the legacy prototype shipped CSS bars
 * with no domain at all for precisely that reason. Every case below is one where
 * a plausible implementation gets a different answer.
 */
import assert from "node:assert/strict";
import test from "node:test";
import { bandPath, bandScale, linePath, linearScale, niceTicks } from "./scale.ts";

test("a linear scale maps the domain onto the range", () => {
  const scale = linearScale([0, 100], [0, 200]);
  assert.equal(scale(0), 0);
  assert.equal(scale(50), 100);
  assert.equal(scale(100), 200);
});

test("a linear scale handles an inverted range, which is every y axis", () => {
  // SVG y grows downward, so a chart's y scale runs from height to zero. Getting
  // this backwards draws every chart upside down, and a mirrored trend line is
  // still a plausible-looking trend line.
  const y = linearScale([0, 10], [100, 0]);
  assert.equal(y(0), 100);
  assert.equal(y(10), 0);
  assert.equal(y(5), 50);
});

test("out-of-domain values clamp instead of drawing outside the plot", () => {
  const scale = linearScale([0, 10], [0, 100]);
  assert.equal(scale(20), 100);
  assert.equal(scale(-5), 0);
  // Clamped on an inverted range too, where min and max of the range swap.
  const y = linearScale([0, 10], [100, 0]);
  assert.equal(y(20), 0);
  assert.equal(y(-5), 100);
});

test("a zero-width domain does not divide by zero", () => {
  // A single-day window, or a metric that has not moved. Both are real and both
  // produce NaN geometry in the obvious implementation — and NaN in a path
  // attribute makes the whole element vanish silently.
  const scale = linearScale([5, 5], [0, 100]);
  assert.equal(scale(5), 0);
  assert.ok(Number.isFinite(scale(5)));
});

test("invert round-trips a value through the scale", () => {
  const scale = linearScale([0, 250], [0, 500]);
  assert.equal(scale.invert(scale(120)), 120);
});

test("a band scale divides the width evenly and centres each band", () => {
  const band = bandScale(4, 400, 0.2);
  assert.equal(band.step, 100);
  assert.equal(band.bandwidth, 80);
  // 10px of the 20px gap sits before the first band, so the row is symmetric.
  assert.equal(band(0), 10);
  assert.equal(band(3), 310);
  // The last band must end inside the width, or it clips at the plot edge.
  assert.ok(band(3) + band.bandwidth <= 400);
});

test("a band scale survives a zero count", () => {
  // An empty result set is a normal state, not an error, and it must not produce
  // an Infinity step that poisons every subsequent coordinate.
  const band = bandScale(0, 400);
  assert.ok(Number.isFinite(band.step));
  assert.equal(band.count, 1);
});

test("ticks land on 1, 2 or 5 times a power of ten", () => {
  assert.deepEqual(niceTicks(0, 10, 5), [0, 2, 4, 6, 8, 10]);
  assert.deepEqual(niceTicks(0, 1, 5), [0, 0.2, 0.4, 0.6, 0.8, 1]);
  // A domain of 0–47 must not produce ticks at 9.4.
  const ticks = niceTicks(0, 47, 5);
  assert.deepEqual(ticks, [0, 10, 20, 30, 40, 50]);
});

test("ticks always cover the domain", () => {
  // An axis whose last tick falls short of the data draws a gridline that stops
  // before the tallest bar, which reads as the bar being off-scale.
  for (const [min, max] of [
    [0, 7],
    [0, 12345],
    [3, 19],
    [-5, 5],
  ] as const) {
    const ticks = niceTicks(min, max);
    assert.ok(ticks.length > 0, `no ticks for ${min}..${max}`);
    assert.ok((ticks[0] as number) <= min, `${ticks[0]} > ${min}`);
    assert.ok((ticks[ticks.length - 1] as number) >= max, `${ticks[ticks.length - 1]} < ${max}`);
  }
});

test("ticks do not accumulate floating-point noise", () => {
  // Repeated addition of 0.1 lands on 2.0000000000000004, which formats as a
  // tick label with sixteen digits on a real axis.
  for (const tick of niceTicks(0, 1, 10)) {
    assert.ok(String(tick).length <= 6, `tick ${tick} has accumulated noise`);
  }
});

test("a degenerate domain yields a single tick, not an infinite loop", () => {
  assert.deepEqual(niceTicks(5, 5), [5]);
  assert.deepEqual(niceTicks(Number.NaN, 10), []);
});

test("a reversed domain is handled rather than returning nothing", () => {
  assert.deepEqual(niceTicks(10, 0, 5), niceTicks(0, 10, 5));
});

test("an empty series draws nothing rather than a misleading dot", () => {
  const x = bandScale(0, 100);
  const y = linearScale([0, 1], [10, 0]);
  // `M0,0` would render a single point that looks like one real observation.
  assert.equal(linePath([], x, y), "");
  assert.equal(bandPath([], [], x, y), "");
});

test("a line path visits every point in order", () => {
  const x = bandScale(3, 300, 0);
  const y = linearScale([0, 10], [100, 0]);
  const path = linePath([0, 5, 10], x, y);
  assert.match(path, /^M/);
  assert.equal(path.split("L").length, 3, path);
  // First point at the bottom, last at the top: the series rises.
  assert.ok(path.includes(",100"), path);
  assert.ok(path.includes(",0"), path);
});

test("a band path closes, and refuses mismatched series", () => {
  const x = bandScale(3, 300, 0);
  const y = linearScale([0, 10], [100, 0]);
  assert.match(bandPath([1, 2, 3], [4, 5, 6], x, y), /Z$/);
  // Mismatched lengths would close the shape across the plot and read as a
  // region nobody intended — better to draw nothing than to draw a lie.
  assert.equal(bandPath([1, 2], [4, 5, 6], x, y), "");
});
