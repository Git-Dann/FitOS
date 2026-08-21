"use client";

/**
 * Open gaps ranked by exposure, drawn as ranges on a shared scale.
 *
 * This is the panel that answers Concept B's hardest objection to itself: "There
 * is no obvious home for confidence or exposure ranges — a coloured cell has no
 * room for '±'." The answer is that the grid does not try to carry them, and
 * this panel does nothing else.
 *
 * Every rule from `gap-model.md` §3 is structural here rather than incidental:
 *
 *   - The mark is a **range**, low to high, on a shared axis. There is no bar
 *     from zero, because a bar from zero to a base figure is a point estimate
 *     wearing a chart's clothes.
 *   - The confidence band sits on the row, adjacent, always.
 *   - A modelled figure is marked, before the number.
 *   - A gap with no exposure says so and is ranked last, rather than being
 *     dropped — a data-quality gap missing from a money view is how a data
 *     problem becomes invisible.
 *
 * The shared axis is the point of drawing this at all. Eight exposure ranges as
 * text are eight numbers to hold in your head; on one scale, the comparison is
 * the picture. That is also why the axis is labelled with real currency ticks
 * rather than being implied.
 */
import { linearScale, niceTicks } from "@fitos/charts";
import { hasExposure, type DemoGap } from "@/lib/demo-gaps";
import { ConfidenceMeter, ModelledMark } from "../chips";
import { exposureRange, money } from "@/lib/format";

const PLOT_WIDTH = 100;

export function ExposureRanking({ gaps }: { gaps: DemoGap[] }) {
  const priced = gaps.filter(hasExposure);
  const unpriced = gaps.filter((gap) => !hasExposure(gap));

  // Rank by the top of the range, not the base. Ranking by base would put a
  // narrow, confident gap above a wide one whose worst case is far larger, and
  // the worst case is what a manager is deciding about.
  const ranked = [...priced].sort((a, b) => b.exposureHigh - a.exposureHigh);

  if (ranked.length === 0) {
    return (
      <p className="chart-empty">
        Nothing in view carries a monetary figure. That is a complete answer, not a missing one — a
        data-quality gap has no exposure because attaching one would mean inventing it.
      </p>
    );
  }

  const currency = ranked[0]?.currency ?? "GBP";
  const max = Math.max(...ranked.map((gap) => gap.exposureHigh));
  const ticks = niceTicks(0, max, 3);
  const domainMax = ticks[ticks.length - 1] ?? max;
  const x = linearScale([0, domainMax], [0, PLOT_WIDTH]);

  return (
    <div className="ranking">
      {/* The axis. Currency ticks, tabular, so the scale is stated rather than
          left to be inferred from the longest bar. */}
      <div className="ranking-axis" aria-hidden="true">
        {ticks.map((tick) => (
          <span key={tick} className="ranking-tick tabular" style={{ left: `${x(tick)}%` }}>
            {money(tick, currency)}
          </span>
        ))}
      </div>

      {ranked.map((gap) => (
        <div key={gap.id} className="ranking-row">
          <span className="ranking-label">
            <span className="mono mono-meta">{gap.reference}</span>
            <span className="ranking-scope">{gap.scopeId}</span>
          </span>

          <span className="ranking-track">
            {ticks.map((tick) => (
              <span
                key={tick}
                className="ranking-gridline"
                style={{ left: `${x(tick)}%` }}
                aria-hidden="true"
              />
            ))}
            {/* Low to high. The base is a tick on the range, not a bar end, so
                nothing here reads as a single precise figure. */}
            <span
              className="ranking-range"
              style={{
                left: `${x(gap.exposureLow)}%`,
                width: `${Math.max(0.8, x(gap.exposureHigh) - x(gap.exposureLow))}%`,
              }}
              aria-hidden="true"
            />
            {typeof gap.exposureBase === "number" ? (
              <span
                className="ranking-base"
                style={{ left: `${x(gap.exposureBase)}%` }}
                title={`Base ${money(gap.exposureBase, gap.currency)}`}
                aria-hidden="true"
              />
            ) : null}
          </span>

          <span className="ranking-value tabular">
            {gap.isModelled ? <ModelledMark /> : null}
            {exposureRange(gap.exposureLow, gap.exposureHigh, gap.currency)}
          </span>
          {/* §3: never without its confidence band, on every surface. */}
          <ConfidenceMeter band={gap.confidenceBand} score={gap.confidenceScore} />
        </div>
      ))}

      {unpriced.length > 0 ? (
        <p className="ranking-unpriced">
          {unpriced.length} more open {unpriced.length === 1 ? "gap carries" : "gaps carry"} no
          monetary figure and {unpriced.length === 1 ? "is" : "are"} not ranked here:{" "}
          {unpriced.map((gap) => gap.reference).join(", ")}. They are not less important — a stopped
          counter has no price and still invalidates every metric scoped to it.
        </p>
      ) : null}
    </div>
  );
}
