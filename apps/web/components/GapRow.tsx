"use client";

/**
 * One gap, as a row.
 *
 * The first version of this row put nine values on two lines, all of them at
 * 11–13px, all of them the same weight. It was dense, which the design system
 * asks for, but density without hierarchy is just small text: severity was a
 * chip the size of a timestamp, and exposure — the figure that decides which
 * gap gets picked up — was the same grey as the scope label beside it.
 *
 * The row now has three tiers and they are meant to be readable in that order:
 *
 *   1. What is wrong. Title at `text-base`, with a severity rail down the left
 *      edge carrying weight that a chip cannot. Colour is never the only cue —
 *      the rail is redundant with the glyph and the word (§9).
 *   2. What it costs, right-aligned in its own column, with confidence
 *      directly beneath it because gap-model.md §3 requires them adjacent.
 *   3. What to do about it — the first `recommended_actions` entry. This is
 *      the answer to "so what", and it was previously in the fixture and
 *      nowhere on screen.
 *
 * Everything else — type, scope, age, status, owner — is metadata and reads as
 * metadata, on one muted line.
 */
import type { DemoGap } from "@/lib/demo-gaps";
import { ConfidenceMeter, ExposureCell, StatusChip } from "./chips";
import { age, shortDate } from "@/lib/format";

export function GapRow({
  gap,
  active,
  onActivate,
  onFocus,
  rowRef,
}: {
  gap: DemoGap;
  active: boolean;
  onActivate: () => void;
  onFocus: () => void;
  rowRef: (element: HTMLButtonElement | null) => void;
}) {
  const action = gap.recommendedActions[0];

  return (
    <button
      type="button"
      className={`gap-row gap-row-${gap.severity}`}
      // aria-current, not aria-selected: aria-selected is not valid on an
      // implicit button role, and "this is the row you are on" is what
      // aria-current means.
      aria-current={active ? "true" : undefined}
      ref={rowRef}
      onClick={onActivate}
      onFocus={onFocus}
    >
      {/* The rail is decoration in the accessibility tree and weight on the
          screen. The severity word is carried in the metadata line below. */}
      <span className="gap-rail" aria-hidden="true" />

      <span className="gap-main">
        <span className="gap-title">{gap.title}</span>
        <span className="gap-meta tabular">
          <span className="gap-meta-strong">{gap.severity}</span>
          <span aria-hidden="true">·</span>
          <span className="gap-meta-secondary">{gap.gapTypeLabel}</span>
          <span className="gap-meta-secondary" aria-hidden="true">
            ·
          </span>
          <span className="gap-meta-strong">{gap.scopeId}</span>
          <span aria-hidden="true">·</span>
          {/* The age of the newest contributing source record, not the row's
              write time. "How old is what this is based on" is the triage
              question; the write time is always now and tells nobody anything. */}
          <span>
            {gap.dataFreshnessSeconds === null
              ? "age unknown"
              : `${age(gap.dataFreshnessSeconds)} old`}
          </span>
          <span className="gap-meta-secondary" aria-hidden="true">
            ·
          </span>
          <span className="gap-meta-secondary">first seen {shortDate(gap.firstSeenAt)}</span>
          <span aria-hidden="true">·</span>
          <span>{gap.ownerInitials ? `owner ${gap.ownerInitials}` : "unowned"}</span>
        </span>
        {action ? (
          <span className="gap-action">
            <span className="gap-action-glyph" aria-hidden="true">
              ▸
            </span>
            <span className="gap-action-title">{action.title}</span>
            <span className="gap-action-rationale">{action.rationale}</span>
          </span>
        ) : null}
      </span>

      <span className="gap-side">
        {/* Exposure and confidence are adjacent by construction, in that order,
            on every surface — see gap-model.md §3. */}
        <span className="gap-exposure">
          <ExposureCell gap={gap} />
        </span>
        <ConfidenceMeter band={gap.confidenceBand} score={gap.confidenceScore} />
        <span className="gap-side-row">
          <StatusChip status={gap.status} />
          <span className="gap-ref tabular">{gap.reference}</span>
        </span>
      </span>
    </button>
  );
}
