/**
 * Status, severity, confidence and exposure chips.
 *
 * Three rules from the design system shape all of these:
 *
 * §9 — status is never carried by colour alone. Every chip has a glyph and a
 * word, so it survives greyscale, colour blindness and a screenshot printed in
 * black and white.
 *
 * §2 (accent discipline) — accent is reserved for interaction. Severity uses
 * the status ramp; nothing here borrows accent to look urgent.
 *
 * The chip-with-a-word treatment is gone entirely. The source design system
 * says it twice — "Use the iconographic status system (drawn glyphs) instead of
 * colored fills or text badges" and "Don't use colored status badges with text
 * — the drawn icon system *is* the language" — and it is right for a reason
 * beyond taste: a chip spent about 60px of row width restating what a 16px
 * glyph says, on the component most of the pixels go to. The glyphs live in
 * `glyphs.tsx`; what is left here is exposure and confidence.
 */
import { hasExposure } from "@/lib/demo-gaps";
import { SeverityGlyph, StatusGlyph } from "./glyphs";
import type { ConfidenceBand, DemoGap, GapStatus, Severity } from "@/lib/demo-gaps";
import { exposureRange, money } from "@/lib/format";

/**
 * A drawn glyph plus a neutral word, for surfaces that have room to name the
 * state — the peek header and the detail route.
 *
 * §7: "Don't use colored status badges with text — the drawn icon system *is*
 * the language." So this is not a chip: no border, no fill, no uppercase, no
 * coloured label. The glyph carries the state and the word names it, which is
 * also what keeps the pair legible in greyscale (§9).
 */
export function StatusLabel({ status }: { status: GapStatus }) {
  return (
    <span className="state-label">
      <StatusGlyph status={status} />
      {status}
    </span>
  );
}

export function SeverityLabel({ severity }: { severity: Severity }) {
  return (
    <span className="state-label">
      <SeverityGlyph severity={severity} />
      {severity}
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
  return (
    <span
      className={`confidence confidence-${band}`}
      title={`Confidence ${band} (${score.toFixed(3)})`}
    >
      <span className="confidence-track" aria-hidden="true">
        <span className="confidence-fill" style={{ width: `${Math.round(score * 100)}%` }} />
      </span>
      <span className="confidence-band">{band}</span>
    </span>
  );
}

/**
 * The mark that says a figure is modelled rather than counted.
 *
 * It goes *before* the number, not after. A marker trailing a value reads as
 * punctuation; a marker leading it reads as a qualifier — and this one has to
 * be read as a qualifier, because §2 requires modelled and observed data to be
 * distinguishable and the row is full of observed percentages carrying no mark
 * at all. `ModelledKey` puts one sentence on the route explaining it, so the
 * distinction is learnable rather than folkloric.
 */
export function ModelledMark() {
  return (
    <span className="modelled-mark" title="Modelled from at least one assumption">
      <span aria-hidden="true">▨</span>
      <span className="visually-hidden">modelled: </span>
    </span>
  );
}

export function ModelledKey() {
  return (
    <span className="modelled-key">
      <span aria-hidden="true">▨</span> modelled from an assumption · everything else is counted
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
      {gap.isModelled ? <ModelledMark /> : null}
      {exposureRange(gap.exposureLow, gap.exposureHigh, gap.currency)}
    </span>
  );
}

export function ExposureBase({ gap }: { gap: DemoGap }) {
  if (typeof gap.exposureBase !== "number" || !gap.currency) return null;
  return <>{money(gap.exposureBase, gap.currency)}</>;
}
