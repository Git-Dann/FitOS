/**
 * Status, severity, confidence and exposure chips.
 *
 * Two rules from the design system shape all of these:
 *
 * §9 — status is never carried by colour alone. Every chip has a glyph and a
 * word, so it survives greyscale, colour blindness and a screenshot printed in
 * black and white.
 *
 * §2 (accent discipline) — accent is reserved for interaction. Severity uses
 * the status ramp; nothing here borrows accent to look urgent.
 */
import { hasExposure } from "@/lib/demo-gaps";
import type { ConfidenceBand, DemoGap, GapStatus, Severity } from "@/lib/demo-gaps";
import { exposureRange, money } from "@/lib/format";

const SEVERITY_GLYPH: Record<Severity, string> = {
  critical: "▲",
  high: "●",
  medium: "◆",
  low: "▪",
  info: "·",
};

export function SeverityChip({ severity }: { severity: Severity }) {
  return (
    <span className={`chip chip-${severity}`}>
      <span className="chip-glyph" aria-hidden="true">
        {SEVERITY_GLYPH[severity]}
      </span>
      {severity}
    </span>
  );
}

const STATUS_GLYPH: Record<GapStatus, string> = {
  detected: "◌",
  triaged: "◔",
  investigating: "◑",
  actioned: "◕",
  validating: "◕",
  resolved: "●",
  dismissed: "✕",
};

export function StatusChip({ status }: { status: GapStatus }) {
  return (
    <span className="chip">
      <span className="chip-glyph" aria-hidden="true">
        {STATUS_GLYPH[status]}
      </span>
      {status}
    </span>
  );
}

/**
 * Confidence as four pips plus the band word.
 *
 * The number is deliberately not the headline. A score of 0.905 invites
 * comparison at a precision the model does not support; the band is the
 * decision-grade summary, and the exact score is in the peek with its
 * component breakdown.
 */
export function ConfidenceMeter({ band, score }: { band: ConfidenceBand; score: number }) {
  const filled = Math.max(1, Math.min(4, Math.round(score * 4)));
  return (
    <span className="confidence" title={`Confidence ${band} (${score.toFixed(3)})`}>
      <span className="confidence-pips" aria-hidden="true">
        {[0, 1, 2, 3].map((index) => (
          <i key={index} className={index < filled ? "pip pip-on" : "pip"} />
        ))}
      </span>
      <span>{band}</span>
    </span>
  );
}

/**
 * An exposure, always as a range, never without its confidence adjacent.
 *
 * design-concepts.md, information hierarchy: "Exposure never appears without
 * its confidence adjacent." That is why this component takes the gap rather
 * than three numbers — it cannot be rendered in isolation by accident.
 *
 * A gap with no exposure says so. It is not an error and not a blank: a
 * data-quality gap has no monetary figure because attaching one would mean
 * inventing it.
 */
export function ExposureCell({ gap }: { gap: DemoGap }) {
  if (!hasExposure(gap)) {
    // Two different sentences, and they must not look alike: a gap with no
    // monetary figure, versus a caller who may not see one.
    return <span className="exposure-none">{gap.exposureLow === null ? "no exposure" : "—"}</span>;
  }
  return (
    <span className="exposure">
      {exposureRange(gap.exposureLow, gap.exposureHigh, gap.currency)}
      {gap.isModelled ? (
        <span className="modelled-mark" title="Modelled from at least one assumption">
          {" "}
          ▨
        </span>
      ) : null}
    </span>
  );
}

export function ExposureBase({ gap }: { gap: DemoGap }) {
  if (typeof gap.exposureBase !== "number" || !gap.currency) return null;
  return <>{money(gap.exposureBase, gap.currency)}</>;
}
