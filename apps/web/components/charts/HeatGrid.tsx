"use client";

/**
 * The pressure grid — Concept B's signature element.
 *
 * Rows are gaps, columns are hours, and a cell is a *pressure band*: within its
 * expected band, above it, well above it, or unknown. Deliberately not a metric
 * value, because Concept B's own Risks section names the failure this could
 * become: "Heat grids invite pattern-matching without evidence, which is the
 * exact failure mode this product exists to prevent."
 *
 * Three things keep it on the right side of that line.
 *
 * A cell makes no causal claim. It says a scope was outside its expected band in
 * an hour. It does not say why, and CLAUDE.md's rule stands — only a
 * `controlled_test` outcome may use causal language, and a coloured square is
 * not a controlled test.
 *
 * A cell is a route to the evidence, not a substitute for it. Every cell is a
 * real link into the gap that owns it, where the metric version, the detector
 * version and the evidence rows live. Pattern-matching without evidence is
 * prevented by making the evidence one click from the pattern.
 *
 * A missing reading is drawn, not skipped. `null` renders as a marked cell with
 * a diagonal, because the concept sketch's `⚠ no data` is the whole reason a
 * heat grid earns its place here: it "naturally surfaces data-quality holes as
 * visible gaps in the grid rather than as an absence of rows". An hour that did
 * not report and an hour that was quiet must never look the same — that is the
 * no-silent-failure rule at the scale of one square.
 */
import { Fragment } from "react";
import Link from "next/link";
import { PRESSURE_LABEL, RADAR_HOURS, type Pressure, type RadarRow } from "@/lib/demo-radar";
import type { DemoGap } from "@/lib/demo-gaps";

function bandClass(cell: Pressure): string {
  if (cell === null) return "cell cell-unknown";
  return `cell cell-${cell}`;
}

function cellTitle(row: RadarRow, hour: string, cell: Pressure): string {
  if (cell === null) {
    return `${row.scopeId}, ${hour}:00 — no reading arrived for this hour`;
  }
  return `${row.scopeId}, ${hour}:00 — ${PRESSURE_LABEL[cell]}`;
}

export function HeatGrid({ rows, gaps }: { rows: RadarRow[]; gaps: DemoGap[] }) {
  const byReference = new Map(gaps.map((gap) => [gap.reference, gap]));

  return (
    <div className="heat">
      {/* One CSS grid for the whole thing — label column plus one track per
          hour — rather than a flex row per gap. Flex rows aligned by accident:
          adjacent cells of the same band in a column ran together into a single
          vertical block, so the picture implied a duration that no row actually
          reported. A shared grid template makes column alignment structural. */}
      <div
        className="heat-grid"
        style={{
          gridTemplateColumns: `var(--heat-label-width) repeat(${RADAR_HOURS.length}, 1fr)`,
        }}
      >
        {/* The axis §7 requires: hours labelled, not implied by position. */}
        <span className="heat-axis-spacer" aria-hidden="true" />
        {RADAR_HOURS.map((hour) => (
          <span key={hour} className="heat-axis-tick tabular" aria-hidden="true">
            {hour}
          </span>
        ))}

        {rows.map((row) => {
          const gap = byReference.get(row.reference);
          return (
            <Fragment key={row.reference}>
              <span className="heat-label">
                <span className="heat-ref mono">{row.reference}</span>
                <span className="heat-scope">{row.scopeId}</span>
              </span>
              {row.cells.map((cell, index) => {
                const hour = RADAR_HOURS[index] ?? "";
                const label = cellTitle(row, hour, cell);
                const body = <span className={bandClass(cell)} aria-hidden="true" />;
                // A cell with no gap behind it is not a link, rather than a
                // link that goes nowhere.
                return gap ? (
                  <Link
                    key={index}
                    className="heat-cell"
                    href={`/gaps/${gap.id}`}
                    title={label}
                    aria-label={label}
                  >
                    {body}
                  </Link>
                ) : (
                  <span key={index} className="heat-cell" title={label}>
                    {body}
                  </span>
                );
              })}
            </Fragment>
          );
        })}
      </div>

      {/* The key. Every band carries a word as well as a fill, so the grid
          survives greyscale and colour blindness (§9). */}
      <div className="heat-key">
        {(["normal", "elevated", "pressure"] as const).map((band) => (
          <span key={band} className="heat-key-item">
            <span className={bandClass(band)} aria-hidden="true" />
            {band}
          </span>
        ))}
        <span className="heat-key-item">
          <span className={bandClass(null)} aria-hidden="true" />
          no reading
        </span>
      </div>
    </div>
  );
}
