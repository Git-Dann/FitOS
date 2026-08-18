/**
 * The orientation layer: what is in front of me, and how much of it is real.
 *
 * The ledger answers "which gap next". It does not answer "how bad is today",
 * which is the first question anyone asks on landing — and a list of rows is
 * the least informative possible answer to it. This module computes the
 * answer once, as data, so the strip that draws it cannot quietly invent one.
 *
 * Everything here is constrained by docs/gap-model.md §3, and the constraints
 * are the interesting part:
 *
 *   - Exposure is summed as an *envelope*, low-to-low and high-to-high. The
 *     `base` figures are never added. A summed base is a single precise number
 *     standing on modelled inputs, which is the exact presentation §3 forbids.
 *   - The envelope carries the weakest confidence band it contains, because
 *     "exposure never appears without its confidence band adjacent to it, in
 *     every surface" applies to an aggregate as much as to a row.
 *   - Low-confidence gaps are excluded from the envelope and counted, not
 *     folded in. Folding them in makes a wide guess look like part of a total.
 *   - Two currencies are not added. There is no exchange rate in the gap
 *     aggregate, so inventing one here would be inventing a number.
 *   - If any gap in view has exposure withheld, there is no envelope at all.
 *     A total computed over the subset the caller may see, presented as the
 *     total, is a silent partial — and CLAUDE.md forbids those specifically.
 */
import { hasExposure, SEVERITY_ORDER } from "./demo-gaps";
import type { ConfidenceBand, DemoGap, Severity } from "./demo-gaps";

/** Six hours. The same threshold the "stale" saved view uses. */
export const STALE_SECONDS = 6 * 3600;

const BAND_RANK: Record<ConfidenceBand, number> = { low: 0, medium: 1, high: 2 };

export type ExposureEnvelope =
  /** The caller's payload has no exposure fields. Not zero — absent. */
  | { kind: "withheld" }
  /** Every gap in view is a kind that carries no monetary figure. */
  | { kind: "none" }
  /** Gaps in view price in different currencies; adding them would be a fiction. */
  | { kind: "mixed"; currencies: string[] }
  | {
      kind: "range";
      low: number;
      high: number;
      currency: string;
      /** How many gaps the envelope is built from. */
      contributing: number;
      /** Excluded because their confidence band is low. Reported, never folded in. */
      excludedLowConfidence: number;
      /** In view, but carrying no monetary figure at all. */
      withoutExposure: number;
      /** At least one input was modelled, so the whole envelope is modelled. */
      isModelled: boolean;
      /** The weakest band among the contributing gaps. */
      band: ConfidenceBand;
    };

export interface SituationSummary {
  total: number;
  bySeverity: { severity: Severity; count: number }[];
  exposure: ExposureEnvelope;
  /** Gaps whose newest contributing record is older than `STALE_SECONDS`. */
  stale: number;
  /** Gaps whose age could not be established at all — its own count, because
   *  "we do not know" and "we know it is old" are different sentences. */
  ageUnknown: number;
  unowned: number;
}

function severityCounts(gaps: DemoGap[]): { severity: Severity; count: number }[] {
  return SEVERITY_ORDER.map((severity) => ({
    severity,
    count: gaps.filter((gap) => gap.severity === severity).length,
  })).filter((entry) => entry.count > 0);
}

function envelope(gaps: DemoGap[]): ExposureEnvelope {
  // Withheld is checked first and wins outright. `exposureLow` absent means the
  // field never arrived; `null` means it arrived carrying "no money here".
  if (gaps.some((gap) => gap.exposureLow === undefined)) return { kind: "withheld" };

  const priced = gaps.filter(hasExposure);
  const withoutExposure = gaps.length - priced.length;
  if (priced.length === 0) return { kind: "none" };

  const currencies = [...new Set(priced.map((gap) => gap.currency))].sort();
  if (currencies.length > 1) return { kind: "mixed", currencies };

  const contributing = priced.filter((gap) => gap.confidenceBand !== "low");
  const excludedLowConfidence = priced.length - contributing.length;
  if (contributing.length === 0) return { kind: "none" };

  const band = contributing.reduce<ConfidenceBand>(
    (weakest, gap) =>
      BAND_RANK[gap.confidenceBand] < BAND_RANK[weakest] ? gap.confidenceBand : weakest,
    "high",
  );

  return {
    kind: "range",
    low: contributing.reduce((sum, gap) => sum + gap.exposureLow, 0),
    high: contributing.reduce((sum, gap) => sum + gap.exposureHigh, 0),
    // Narrowed by `hasExposure`; the single-entry `currencies` set above is
    // what proves every contributing gap agrees on it.
    currency: currencies[0] as string,
    contributing: contributing.length,
    excludedLowConfidence,
    withoutExposure,
    isModelled: contributing.some((gap) => gap.isModelled),
    band,
  };
}

export function summarise(gaps: DemoGap[]): SituationSummary {
  return {
    total: gaps.length,
    bySeverity: severityCounts(gaps),
    exposure: envelope(gaps),
    stale: gaps.filter(
      (gap) => gap.dataFreshnessSeconds !== null && gap.dataFreshnessSeconds > STALE_SECONDS,
    ).length,
    ageUnknown: gaps.filter((gap) => gap.dataFreshnessSeconds === null).length,
    unowned: gaps.filter((gap) => gap.ownerInitials === null).length,
  };
}
