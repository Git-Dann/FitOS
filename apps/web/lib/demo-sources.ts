/**
 * Connector state for the sources route.
 *
 * CLAUDE.md: *no fake status — a connector card shows its real state;
 * `fixture` is never dressed as `healthy`.* That rule is why `state` here is a
 * closed set including `fixture`, and why the demonstration sources say plainly
 * that they are fixtures rather than borrowing the healthy badge to look
 * finished. A demo that shows green everywhere teaches the reader that green
 * means nothing.
 */

export type SourceState =
  | "healthy"
  | "degraded"
  | "stale"
  | "failing"
  | "fixture"
  | "never_run"
  | "disabled";

export interface DemoSource {
  key: string;
  label: string;
  connector: string;
  state: SourceState;
  /** Seconds since the newest record, or null when it has never reported. */
  ageSeconds: number | null;
  expectedLatencySeconds: number;
  lastRunAt: string | null;
  recordsAccepted: number;
  recordsRejected: number;
  note: string;
}

export const DEMO_SOURCES: DemoSource[] = [
  {
    key: "pos_csv",
    label: "POS CSV upload",
    connector: "csv_upload",
    state: "healthy",
    ageSeconds: 5400,
    expectedLatencySeconds: 86_400,
    lastRunAt: "2026-08-18T12:30:00Z",
    recordsAccepted: 4820,
    recordsRejected: 0,
    note: "Daily upload, inside its declared cadence.",
  },
  {
    key: "inventory_rest",
    label: "Inventory REST",
    connector: "rest",
    state: "healthy",
    ageSeconds: 1800,
    expectedLatencySeconds: 3600,
    lastRunAt: "2026-08-18T13:30:00Z",
    recordsAccepted: 12_400,
    recordsRejected: 3,
    note: "3 records quarantined with a reason; counts are never silent.",
  },
  {
    key: "footfall_counter",
    label: "Footfall counter",
    connector: "rest",
    state: "stale",
    ageSeconds: 111_600,
    expectedLatencySeconds: 3600,
    lastRunAt: "2026-08-17T07:00:00Z",
    recordsAccepted: 0,
    recordsRejected: 0,
    note: "31 hours behind a declared 1 hour cadence. Raised as NS-007.",
  },
  {
    key: "loyalty_rest",
    label: "Loyalty REST",
    connector: "rest",
    state: "degraded",
    ageSeconds: 3600,
    expectedLatencySeconds: 3600,
    lastRunAt: "2026-08-18T13:00:00Z",
    recordsAccepted: 2050,
    recordsRejected: 2950,
    note: "Arriving on time, but 59% of records are being rejected. Raised as NS-061.",
  },
  {
    key: "finance_export",
    label: "Finance export",
    connector: "csv_upload",
    state: "fixture",
    ageSeconds: null,
    expectedLatencySeconds: 604_800,
    lastRunAt: null,
    recordsAccepted: 0,
    recordsRejected: 0,
    // Not dressed as healthy. It has never connected to anything.
    note: "Demonstration fixture. No credential is configured and no run has happened.",
  },
  {
    key: "ad_platform",
    label: "Ad platform REST",
    connector: "rest",
    state: "fixture",
    ageSeconds: null,
    expectedLatencySeconds: 86_400,
    lastRunAt: null,
    recordsAccepted: 0,
    recordsRejected: 0,
    note: "Demonstration fixture. No credential is configured and no run has happened.",
  },
];

export const SOURCE_STATE_GLYPH: Record<SourceState, string> = {
  healthy: "●",
  degraded: "◐",
  stale: "◔",
  failing: "▲",
  fixture: "▨",
  never_run: "○",
  disabled: "✕",
};
