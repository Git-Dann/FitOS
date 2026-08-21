/**
 * The wrapper every chart in this product goes through.
 *
 * `docs/design-system.md` §7: "Every chart ships with: a scale, an axis, a
 * source attribution, an as-of time, an accessible text summary, and a data
 * table or export path. A chart without all six does not merge — this is the
 * single most-violated rule in the legacy prototype, where CSS `div` bars carry
 * no scale or source at all."
 *
 * A rule violated that often is not a rule people are ignoring; it is a rule the
 * code makes easy to break. So every one of the six is a **required prop** here.
 * `summary`, `source`, `asOf`, `scaleLabel` and `table` have no defaults and are
 * not optional, which means a chart that omits its provenance does not compile.
 * That is a materially different guarantee from a reviewer remembering to check.
 *
 * The `summary` is the part worth being pedantic about. It is not alt text
 * restating the chart type — "a bar chart of exposure" tells a screen-reader
 * user nothing a sighted user does not also get from the title. It is the
 * sentence a colleague would say out loud: what the shape *is*, in numbers. It
 * is rendered visibly as well as exposed to assistive technology, because a
 * sentence good enough for a screen reader is usually the sentence a reader
 * skimming the dashboard wanted anyway.
 */
import type { ReactNode } from "react";

export interface ChartFrameProps {
  /** What the chart is called. */
  title: string;
  /**
   * The domain and unit, stated. §7 requires a scale; a bar at 61% of its track
   * is meaningless without knowing 61% of what.
   */
  scaleLabel: string;
  /** Which source or governed metric the numbers came from. */
  source: string;
  /** The as-of time, already formatted. */
  asOf: string;
  /**
   * One or two sentences describing the shape in numbers. Read by assistive
   * technology and shown to everyone.
   */
  summary: string;
  /** The same data as a table, so the chart is never the only access path. */
  table: ReactNode;
  /** The chart itself. */
  children: ReactNode;
  /**
   * Set when some of the underlying data did not arrive. A partial result
   * rendered as complete is a correctness failure, not a cosmetic one.
   */
  partial?: string | undefined;
  className?: string | undefined;
}

export function ChartFrame({
  title,
  scaleLabel,
  source,
  asOf,
  summary,
  table,
  children,
  partial,
  className,
}: ChartFrameProps) {
  return (
    <figure className={className ? `chart ${className}` : "chart"}>
      <div className="chart-head">
        <h2 className="chart-title">{title}</h2>
        <span className="chart-scale">{scaleLabel}</span>
      </div>

      {/* The partial notice sits above the marks, not below them: by the time
          you have read the chart you have already believed it. */}
      {partial ? (
        <p className="chart-partial">
          <span aria-hidden="true">⚠</span> {partial}
        </p>
      ) : null}

      <div className="chart-plot">{children}</div>

      <figcaption className="chart-caption">
        <p className="chart-summary">{summary}</p>
        <p className="chart-provenance">
          {source} · as of {asOf}
        </p>
        {/* Open by default would double every chart's height; a disclosure keeps
            the table one keystroke away, which §7's "or export path" allows. */}
        <details className="chart-table">
          <summary>Show the numbers</summary>
          {table}
        </details>
      </figcaption>
    </figure>
  );
}
