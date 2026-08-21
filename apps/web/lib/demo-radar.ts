/**
 * Demonstration data for the Operations Radar (Concept B).
 *
 * Fixed arrays, not generated. `Math.random()` in a fixture is a fixture that
 * cannot be screenshot-reviewed and a chart whose shape changes under the
 * reviewer, and a seeded generator here would still be a generator nobody can
 * read. Every number below was chosen to make a specific state visible.
 *
 * Concept B's documented risks are the constraints this file works under:
 *
 *   "Heat grids invite pattern-matching without evidence, which is the exact
 *    failure mode this product exists to prevent."
 *
 * So a cell carries a *pressure band*, not a metric value, and never a
 * direction of causation. A cell is the answer to "was this scope under
 * pressure in this hour" and nothing else; the gap it belongs to carries the
 * evidence, the metric version and the detector version.
 *
 *   "Naturally surfaces data-quality holes as visible gaps in the grid rather
 *    than as an absence of rows."
 *
 * `null` is therefore a real, rendered state — the `⚠ no data` of the concept
 * sketch — and not a hole the grid quietly closes over. A missing hour that
 * renders as "normal" is the silent-failure rule broken in one pixel.
 */

/** Pressure bands, in the concept's own vocabulary. `null` means no reading. */
export type Pressure = "normal" | "elevated" | "pressure" | null;

export interface RadarRow {
  /** The gap this row belongs to, so a cell can reach its evidence. */
  reference: string;
  scopeId: string;
  /** One entry per hour in `RADAR_HOURS`, aligned by index. */
  cells: Pressure[];
}

/**
 * The hours the grid covers, as labels. Eight buckets keeps the grid legible at
 * 1024px, which is the width the concept sketch was drawn at.
 */
export const RADAR_HOURS = ["10", "11", "12", "13", "14", "15", "16", "17"] as const;

export const PRESSURE_LABEL: Record<NonNullable<Pressure>, string> = {
  normal: "within its expected band",
  elevated: "above its expected band",
  pressure: "well above its expected band",
};

/**
 * Rows in the same order the ledger groups them: critical first. The grid is a
 * different view of the same eight gaps, not a different dataset — a dashboard
 * that disagrees with the list it links to is worse than no dashboard.
 */
export const RADAR_ROWS: RadarRow[] = [
  {
    reference: "NS-014",
    scopeId: "Oxford Street",
    cells: ["normal", "normal", "elevated", "pressure", "pressure", "elevated", "normal", "normal"],
  },
  {
    // The footfall counter stopped reporting at 07:00 the previous day, so every
    // hour here is unknown rather than quiet. This is the row that exists to
    // prove the grid distinguishes the two.
    reference: "NS-007",
    scopeId: "footfall_counter",
    cells: [null, null, null, null, null, null, null, null],
  },
  {
    reference: "NS-033",
    scopeId: "iOS 4.2.1",
    cells: [
      "elevated",
      "elevated",
      "pressure",
      "pressure",
      "pressure",
      "pressure",
      "elevated",
      "elevated",
    ],
  },
  {
    // Partial: the loyalty feed delivered 41% of expected records, so four of
    // the eight hours have no reading at all.
    reference: "NS-061",
    scopeId: "loyalty_feed",
    cells: ["elevated", null, "pressure", null, "pressure", null, "elevated", null],
  },
  {
    reference: "NS-021",
    scopeId: "Trafford",
    cells: ["normal", "normal", "elevated", "elevated", "elevated", "normal", "normal", "normal"],
  },
  {
    reference: "NS-045",
    scopeId: "Field Jacket · Stone",
    cells: ["normal", "normal", "normal", "elevated", "elevated", "elevated", "normal", "normal"],
  },
  {
    reference: "NS-052",
    scopeId: "Spring Refresh",
    cells: ["normal", "elevated", "elevated", "normal", "normal", "normal", "normal", "normal"],
  },
  {
    reference: "NS-078",
    scopeId: "Leeds",
    cells: ["normal", "normal", "normal", "elevated", "normal", "normal", "normal", "normal"],
  },
];

export interface Channel {
  key: string;
  label: string;
  /** The governed metric this reads. Named so the strip cites rather than asserts. */
  metricKey: string;
  /** The value as a display string, formatted from the governed layer. */
  reading: string;
  /** Series for the sparkline, oldest first. Unitless — the axis is the label. */
  series: number[];
  /**
   * Change against the previous comparable window, already in the metric's own
   * unit, plus the unit word. `null` means the comparison could not be made —
   * which is not the same as no change, and must not render as "flat".
   */
  delta: { value: number; unit: string } | null;
  /** How many open gaps are scoped to this channel. */
  gapCount: number;
  /**
   * True when this reading cannot be trusted because its own inputs are broken
   * — not when it happens to be measuring something broken.
   *
   * The distinction matters and is easy to collapse. `Stores` conversion is
   * unreliable: its denominator is a footfall counter that stopped 31 hours ago,
   * so the rate is unusable rather than low. `Loyalty` completeness reads 41%
   * *because* a feed is short — the metric is doing its job, and marking it
   * unreliable would suppress the one number that is telling the truth about
   * the outage. A test asserts an unreliable channel draws no line and claims
   * no comparison, which is what caught this being wrong the first time.
   */
  unreliable: boolean;
}

export const CHANNELS: Channel[] = [
  {
    key: "web",
    label: "Web",
    metricKey: "web_conversion_rate",
    reading: "2.1%",
    series: [2.4, 2.3, 2.35, 2.2, 2.15, 2.1],
    delta: { value: -0.2, unit: "pp" },
    gapCount: 1,
    unreliable: false,
  },
  {
    key: "app",
    label: "App",
    metricKey: "checkout_activation_rate",
    reading: "61%",
    series: [79, 78, 74, 68, 63, 61],
    delta: { value: -18, unit: "pp" },
    gapCount: 2,
    unreliable: false,
  },
  {
    key: "stores",
    label: "Stores",
    metricKey: "store_conversion_rate",
    reading: "—",
    // The footfall counter is the denominator. A conversion rate over a stale
    // denominator is not a low reading, it is an unusable one, so there is no
    // series to draw and the strip says so instead of drawing a flat line.
    series: [],
    delta: null,
    gapCount: 1,
    unreliable: true,
  },
  {
    key: "stock",
    label: "Stock",
    metricKey: "stock_discrepancy_rate",
    reading: "4.1%",
    series: [1.8, 2.1, 2.6, 3.2, 3.7, 4.1],
    delta: { value: 2.3, unit: "pp" },
    gapCount: 3,
    unreliable: false,
  },
  {
    key: "loyalty",
    label: "Loyalty",
    metricKey: "data_completeness",
    reading: "41%",
    // Reliable, and alarming. Completeness is measuring the shortfall, so the
    // series is exactly what should be drawn — suppressing it would hide the
    // outage rather than report it.
    series: [98, 97, 96, 88, 62, 41],
    delta: { value: -57, unit: "pp" },
    gapCount: 1,
    unreliable: false,
  },
];

/** Counts the pressure bands across the whole grid, including the unknowns. */
export function pressureTotals(rows: RadarRow[]): {
  normal: number;
  elevated: number;
  pressure: number;
  unknown: number;
} {
  const totals = { normal: 0, elevated: 0, pressure: 0, unknown: 0 };
  for (const row of rows) {
    for (const cell of row.cells) {
      if (cell === null) totals.unknown += 1;
      else totals[cell] += 1;
    }
  }
  return totals;
}
