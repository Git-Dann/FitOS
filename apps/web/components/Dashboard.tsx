"use client";

/**
 * The Operations Radar — Concept B, as the signed-in home.
 *
 * `docs/design-concepts.md` scores this concept `manager ●●● · presenter ●●●`
 * and Concept A (the ledger) `manager ●● · presenter ○`. The ledger stays, at
 * `/inbox`, because Concept B's own Risks are explicit that "triage does not
 * scale: at 10,000 gaps the radar is decoration". The two answer different
 * questions and the nav now says which is which:
 *
 *   Radar — where is it hurting right now, and what does it cost
 *   Inbox — which one do I pick up next
 *
 * The concept's stated risk is that it "drifts toward the generic BI dashboard
 * the brief prohibits, and the pull is strong". What keeps it from doing so is
 * that nothing on this page is a number without a provenance: every panel goes
 * through `ChartFrame`, which will not compile without a scale, a source, an
 * as-of time, an accessible summary and a data table.
 */
import { useMemo } from "react";
import { AppShell } from "./AppShell";
import { ChartFrame } from "./charts/ChartFrame";
import { ChannelStrip } from "./charts/ChannelStrip";
import { ExposureRanking } from "./charts/ExposureRanking";
import { HeatGrid } from "./charts/HeatGrid";
import {
  CHANNELS,
  PRESSURE_LABEL,
  RADAR_HOURS,
  RADAR_ROWS,
  pressureTotals,
} from "@/lib/demo-radar";
import { DEMO_AS_OF, type DemoGap } from "@/lib/demo-gaps";
import { DEMO_SOURCES } from "@/lib/demo-sources";
import { summarise } from "@/lib/situation";
import { count, dateTime, exposureRange, money } from "@/lib/format";

export function Dashboard({ gaps }: { gaps: DemoGap[] }) {
  const asOf = dateTime(DEMO_AS_OF);
  const summary = useMemo(() => summarise(gaps), [gaps]);
  const totals = useMemo(() => pressureTotals(RADAR_ROWS), []);
  const notHealthy = DEMO_SOURCES.filter(
    (source) => source.state !== "healthy" && source.state !== "fixture",
  ).length;

  const { exposure } = summary;

  return (
    <AppShell
      current="/"
      title="Operations"
      inboxCount={gaps.length}
      meta={`as of ${asOf} · ${count(DEMO_SOURCES.length)} sources · ${count(notHealthy)} not healthy`}
      demoNote="Every reading, gap and figure below is fictional."
    >
      <div className="radar">
        <ChartFrame
          className="radar-heat"
          title="Pressure by scope and hour"
          scaleLabel="Band against each scope's own expected range · 8 hours to 17:00"
          source={`${count(RADAR_ROWS.length)} open gaps · detector output, not a metric value`}
          asOf={asOf}
          summary={`Across ${count(RADAR_ROWS.length)} scopes and ${count(RADAR_HOURS.length)} hours: ${count(totals.pressure)} hours well above the expected band, ${count(totals.elevated)} above it, ${count(totals.normal)} within it, and ${count(totals.unknown)} with no reading at all. The heaviest run is iOS 4.2.1, above band for all eight hours. A cell says a scope was outside its band in an hour; it does not say why.`}
          partial={
            totals.unknown > 0
              ? `${count(totals.unknown)} of ${count(RADAR_ROWS.length * RADAR_HOURS.length)} cells have no reading. Those hours are unknown, not quiet — the footfall counter has not reported for 31 hours and the loyalty feed delivered 41% of its records.`
              : undefined
          }
          table={
            <table className="table">
              <caption className="visually-hidden">Pressure band by scope and hour</caption>
              <thead>
                <tr>
                  <th scope="col">Scope</th>
                  {RADAR_HOURS.map((hour) => (
                    <th key={hour} scope="col">
                      {hour}:00
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {RADAR_ROWS.map((row) => (
                  <tr key={row.reference}>
                    <th scope="row">
                      {row.reference} · {row.scopeId}
                    </th>
                    {row.cells.map((cell, index) => (
                      <td key={index}>{cell === null ? "no reading" : PRESSURE_LABEL[cell]}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          }
        >
          <HeatGrid rows={RADAR_ROWS} gaps={gaps} />
        </ChartFrame>

        <ChartFrame
          className="radar-exposure"
          title="Open gaps by estimated exposure"
          scaleLabel={
            exposure.kind === "range"
              ? `Range low to high, shared axis from ${money(0, exposure.currency)} · not a saving`
              : "Range low to high · not a saving"
          }
          source="Governed metrics with a per-gap exposure formula"
          asOf={asOf}
          summary={
            exposure.kind === "range"
              ? `${count(exposure.contributing)} of ${count(summary.total)} open gaps carry a monetary figure, together spanning ${exposureRange(exposure.low, exposure.high, exposure.currency)}. The weakest confidence band among them is ${exposure.band}. Ranking is by the top of each range, because the worst case is what a decision is made against. ${exposure.withoutExposure > 0 ? `${count(exposure.withoutExposure)} carry no figure at all.` : ""}`
              : exposure.kind === "withheld"
                ? "Exposure is absent from this payload. A figure exists and is not yours to see, which is a different thing from there being no figure."
                : "Nothing in view carries a monetary figure."
          }
          table={
            <table className="table">
              <caption className="visually-hidden">Exposure range and confidence by gap</caption>
              <thead>
                <tr>
                  <th scope="col">Gap</th>
                  <th scope="col">Scope</th>
                  <th scope="col">Low</th>
                  <th scope="col">Base</th>
                  <th scope="col">High</th>
                  <th scope="col">Confidence</th>
                  <th scope="col">Modelled</th>
                </tr>
              </thead>
              <tbody>
                {gaps.map((gap) => (
                  <tr key={gap.id}>
                    <th scope="row">{gap.reference}</th>
                    <td>{gap.scopeId}</td>
                    <td className="tabular">
                      {typeof gap.exposureLow === "number" && gap.currency
                        ? money(gap.exposureLow, gap.currency)
                        : gap.exposureLow === null
                          ? "no exposure"
                          : "withheld"}
                    </td>
                    <td className="tabular">
                      {typeof gap.exposureBase === "number" && gap.currency
                        ? money(gap.exposureBase, gap.currency)
                        : "—"}
                    </td>
                    <td className="tabular">
                      {typeof gap.exposureHigh === "number" && gap.currency
                        ? money(gap.exposureHigh, gap.currency)
                        : "—"}
                    </td>
                    <td>{gap.confidenceBand}</td>
                    <td>{gap.isModelled ? "yes" : "observed"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          }
        >
          <ExposureRanking gaps={gaps} />
        </ChartFrame>

        <ChartFrame
          className="radar-channels"
          title="Channels"
          scaleLabel="Each sparkline is scaled to its own series · 6 windows"
          source="Governed metrics, one per channel"
          asOf={asOf}
          summary={`${count(CHANNELS.length)} channels. App checkout activation has fallen 18pp over six windows, the steepest move on the strip. Loyalty completeness is at 41% and still falling — that reading is reliable, and it is the metric reporting the outage rather than a victim of it. Stores has no series at all: its conversion is computed over a footfall denominator that stopped reporting, so no line is drawn rather than a flat one.`}
          partial={`${count(CHANNELS.filter((channel) => channel.unreliable).length)} of ${count(CHANNELS.length)} channels cannot be read at all, because their own inputs are not reporting. That is shown as an absent series, never as a flat line.`}
          table={
            <table className="table">
              <caption className="visually-hidden">Channel readings and change</caption>
              <thead>
                <tr>
                  <th scope="col">Channel</th>
                  <th scope="col">Metric</th>
                  <th scope="col">Reading</th>
                  <th scope="col">Change</th>
                  <th scope="col">Open gaps</th>
                  <th scope="col">Source reliable</th>
                </tr>
              </thead>
              <tbody>
                {CHANNELS.map((channel) => (
                  <tr key={channel.key}>
                    <th scope="row">{channel.label}</th>
                    <td className="mono mono-meta">{channel.metricKey}</td>
                    <td className="tabular">{channel.reading}</td>
                    <td className="tabular">
                      {channel.delta === null
                        ? "no comparison"
                        : `${channel.delta.value > 0 ? "+" : ""}${channel.delta.value}${channel.delta.unit}`}
                    </td>
                    <td className="tabular">{count(channel.gapCount)}</td>
                    <td>{channel.unreliable ? "no" : "yes"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          }
        >
          <ChannelStrip channels={CHANNELS} />
        </ChartFrame>
      </div>
    </AppShell>
  );
}
