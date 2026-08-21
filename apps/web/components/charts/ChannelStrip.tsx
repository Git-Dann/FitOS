"use client";

/**
 * The channel strip along the bottom of the radar.
 *
 * One card per channel: the current reading, a sparkline, the change against the
 * previous comparable window, and how many open gaps are scoped there.
 *
 * The interesting cases are the two that most dashboards get wrong.
 *
 * **A channel whose source is not reporting draws no line.** `Stores` reads its
 * conversion over a footfall denominator that stopped 31 hours ago. A flat line
 * there would be a lie of the most convincing kind — it looks like stability.
 * So the sparkline is replaced by a stated reason, and the reading is an em
 * dash rather than a number.
 *
 * **A delta of `null` is not zero.** "We could not compare" and "nothing
 * changed" are different sentences, and rendering the first as `flat` is the
 * silent-failure rule broken in two characters. The concept sketch itself shows
 * `flat` for the stores column; that is the one detail of the sketch this
 * implementation deliberately does not copy.
 *
 * Every number is a governed metric read by key. No component here computes an
 * analytical value — CLAUDE.md: "No analytical value, formula or currency
 * literal in a React component. Metrics come from the governed layer."
 */
import { bandScale, linePath, linearScale } from "@fitos/charts";
import type { Channel } from "@/lib/demo-radar";

const SPARK_WIDTH = 72;
const SPARK_HEIGHT = 20;

function Sparkline({ series, label }: { series: number[]; label: string }) {
  if (series.length < 2) return null;

  const min = Math.min(...series);
  const max = Math.max(...series);
  // A flat series has a zero-width domain. Padding it keeps the line on the
  // centreline instead of pinning it to an edge, where a genuinely flat metric
  // would look like it was at its minimum.
  const pad = max === min ? Math.max(1, Math.abs(max) * 0.1) : 0;
  const x = bandScale(series.length, SPARK_WIDTH, 0);
  const y = linearScale([min - pad, max + pad], [SPARK_HEIGHT - 1, 1]);

  return (
    <svg
      className="spark"
      width={SPARK_WIDTH}
      height={SPARK_HEIGHT}
      viewBox={`0 0 ${SPARK_WIDTH} ${SPARK_HEIGHT}`}
      role="img"
      aria-label={label}
    >
      <path d={linePath(series, x, y)} fill="none" strokeWidth={1.5} strokeLinejoin="round" />
      {/* The latest point, marked. Without it a sparkline's right-hand end is
          ambiguous between "the series stops here" and "it is cropped". */}
      <circle cx={x(series.length - 1)} cy={y(series[series.length - 1] as number)} r={1.8} />
    </svg>
  );
}

/** The direction word. Never a colour alone, and never a causal verb. */
function deltaLabel(delta: Channel["delta"]): string {
  if (delta === null) return "no comparison available";
  if (delta.value === 0) return `unchanged (0${delta.unit})`;
  const direction = delta.value > 0 ? "up" : "down";
  return `${direction} ${Math.abs(delta.value)}${delta.unit} on the previous window`;
}

export function ChannelStrip({ channels }: { channels: Channel[] }) {
  return (
    <div className="channels">
      {channels.map((channel) => (
        <div key={channel.key} className="channel">
          <p className="channel-label">{channel.label}</p>
          <p className="channel-reading tabular">{channel.reading}</p>

          {channel.series.length >= 2 ? (
            <Sparkline
              series={channel.series}
              label={`${channel.label}: ${channel.series.length} readings, ${deltaLabel(channel.delta)}`}
            />
          ) : (
            <p className="channel-nodata">
              <span aria-hidden="true">⚠</span> no series — its source is not reporting
            </p>
          )}

          <p className="channel-delta">
            {channel.delta === null ? (
              <span className="channel-nocompare">no comparison</span>
            ) : (
              <span className="tabular">
                {channel.delta.value > 0 ? "+" : ""}
                {channel.delta.value}
                {channel.delta.unit}
              </span>
            )}
          </p>

          <p className="channel-gaps">
            {channel.gapCount === 0
              ? "no open gaps"
              : `${channel.gapCount} open ${channel.gapCount === 1 ? "gap" : "gaps"}`}
          </p>
          {/* The metric key, so the strip cites rather than asserts. */}
          <p className="channel-metric mono mono-meta">{channel.metricKey}</p>
        </div>
      ))}
    </div>
  );
}
