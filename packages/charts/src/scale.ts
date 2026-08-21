/**
 * Scales and ticks, as pure functions.
 *
 * `docs/design-system.md` §7 requires every chart to ship with a scale, an axis,
 * a source attribution, an as-of time, an accessible text summary and a data
 * table — and calls it "the single most-violated rule in the legacy prototype,
 * where CSS `div` bars carry no scale or source at all."
 *
 * Two halves solve that. This module is the first: the maths, with no React and
 * no DOM, so a scale that maps a value to the wrong pixel is caught by a test
 * rather than by an eye that has no way to tell 61% from 67% in a bar. The
 * second half is `ChartFrame` in the web app, which makes the other five parts
 * of the contract *required props* — a chart that omits its source or its as-of
 * time does not compile, which is a stronger guarantee than a review checklist.
 *
 * The legacy prototype's bars were `width: 61%` with no axis and no domain. The
 * point of a scale object is that the domain is stated, so a reader can tell
 * whether a bar reaching halfway means "half of the maximum in view" or "half of
 * a fixed target" — those are different claims and a bare percentage hides which
 * one is being made.
 */

export interface LinearScale {
  /** Maps a domain value to a range value, clamped to the range. */
  (value: number): number;
  domain: readonly [number, number];
  range: readonly [number, number];
  /** The inverse, for hit-testing a pointer position back to a value. */
  invert: (position: number) => number;
}

/**
 * A clamped linear scale.
 *
 * Clamping is deliberate. An unclamped scale silently draws outside its plot
 * area when a value exceeds the domain — the mark is still visible, so it looks
 * like data rather than like an error. Clamped, an out-of-domain value pins to
 * the edge, which reads as "at or beyond the limit" and is the honest rendering.
 * A caller that needs to know it happened should widen the domain.
 */
export function linearScale(
  domain: readonly [number, number],
  range: readonly [number, number],
): LinearScale {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  // A zero-width domain has no gradient. Mapping everything to the range start
  // is the only answer that does not divide by zero or invent a spread.
  const span = d1 - d0;

  const scale = ((value: number) => {
    if (span === 0) return r0;
    const t = (value - d0) / span;
    const position = r0 + t * (r1 - r0);
    const lo = Math.min(r0, r1);
    const hi = Math.max(r0, r1);
    return Math.min(hi, Math.max(lo, position));
  }) as LinearScale;

  scale.domain = domain;
  scale.range = range;
  scale.invert = (position: number) => {
    if (r1 - r0 === 0) return d0;
    return d0 + ((position - r0) / (r1 - r0)) * span;
  };
  return scale;
}

export interface BandScale {
  /** The left edge of the band at `index`. */
  (index: number): number;
  bandwidth: number;
  step: number;
  count: number;
}

/**
 * Evenly spaced bands with a proportional gap, for categorical axes.
 *
 * `padding` is the share of each step given to the gap, so 0.2 leaves 80% of the
 * step as bar. Expressing it as a ratio rather than as pixels keeps the bars
 * proportional when the chart is resized, which is what stops a responsive bar
 * chart from turning into hairlines on a phone.
 */
export function bandScale(count: number, width: number, padding = 0.2): BandScale {
  const safeCount = Math.max(1, Math.floor(count));
  const step = width / safeCount;
  const bandwidth = Math.max(0, step * (1 - padding));
  const offset = (step - bandwidth) / 2;

  const scale = ((index: number) => index * step + offset) as BandScale;
  scale.bandwidth = bandwidth;
  scale.step = step;
  scale.count = safeCount;
  return scale;
}

/**
 * Axis ticks at 1, 2 or 5 times a power of ten, covering the domain.
 *
 * "Nice" numbers are not cosmetic. A tick at 3,847 invites the reader to believe
 * the number matters; a tick at 4,000 reads as a gridline. The returned array
 * always spans the domain, so an axis drawn from it cannot end before the data.
 */
export function niceTicks(min: number, max: number, target = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  if (min === max) return [min];
  if (min > max) return niceTicks(max, min, target);

  const rawStep = (max - min) / Math.max(1, target);
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const normalised = rawStep / magnitude;
  const factor = normalised <= 1 ? 1 : normalised <= 2 ? 2 : normalised <= 5 ? 5 : 10;
  const step = factor * magnitude;

  const first = Math.floor(min / step) * step;
  // The last tick must sit at or above `max`, not at or below it. Stopping
  // below leaves an axis whose final gridline falls short of the tallest bar,
  // which reads as the bar being off-scale rather than as the axis being short.
  const last = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  // Indexed multiplication rather than repeated addition: adding 0.1 twenty
  // times lands on 2.0000000000000004, which formats as a tick label with
  // sixteen digits.
  for (let i = 0; first + i * step <= last + step * 1e-9; i += 1) {
    ticks.push(Number((first + i * step).toPrecision(12)));
    if (ticks.length > 1000) break;
  }
  return ticks;
}

/**
 * The path for a polyline through `values`, for a sparkline.
 *
 * Returns an empty string for an empty series rather than a degenerate path,
 * because `<path d="">` draws nothing while `<path d="M0,0">` draws a dot that
 * looks like a single real observation.
 */
export function linePath(
  values: readonly number[],
  x: BandScale | LinearScale,
  y: LinearScale,
): string {
  if (values.length === 0) return "";
  return values
    .map((value, index) => `${index === 0 ? "M" : "L"}${round(x(index))},${round(y(value))}`)
    .join(" ");
}

/**
 * The path for a band between two series — an exposure low/high envelope.
 *
 * The two series must be the same length; a band drawn from mismatched arrays
 * closes across the plot and reads as a shape nobody intended.
 */
export function bandPath(
  low: readonly number[],
  high: readonly number[],
  x: BandScale | LinearScale,
  y: LinearScale,
): string {
  if (low.length === 0 || low.length !== high.length) return "";
  const top = high.map(
    (value, index) => `${index === 0 ? "M" : "L"}${round(x(index))},${round(y(value))}`,
  );
  const bottom = [...low]
    .map((value, index) => ({ value, index }))
    .reverse()
    .map(({ value, index }) => `L${round(x(index))},${round(y(value))}`);
  return [...top, ...bottom, "Z"].join(" ");
}

/** Two decimals is sub-pixel at every viewport and keeps the markup readable. */
function round(value: number): number {
  return Number(value.toFixed(2));
}
