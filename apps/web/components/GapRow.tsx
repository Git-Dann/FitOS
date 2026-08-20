"use client";

/**
 * One gap, as a row — the signature element.
 *
 * DESIGN.md §4, Issue Row, is followed literally:
 *
 *   "Layout: 16pt status icon → 13pt mono identifier → 15pt title (1-line,
 *    ellipsized) → flex spacer → priority bars → 20pt assignee avatar"
 *   "Height: 44pt (compact) / 52pt (comfortable)"
 *   "Selected: background rgba(94,106,210,0.14), 2pt #5E6AD2 left accent inset"
 *   "Pressed: background #232428, no scale (speed > flourish)"
 *
 * The trailing zone is where a gap differs from an issue: between the priority
 * bars and the avatar it carries the exposure and its confidence, which
 * gap-model.md §3 requires to be adjacent on every surface. That is the only
 * addition to the source layout, and it sits in the slot the spec leaves for
 * right-aligned numerics.
 *
 * Comfortable density (52pt) adds the recommended-action line. The previous
 * build put that line on every row, which made a three-line row and cost the
 * density the spec calls "the value proposition" — §7: "Don't pad issue rows
 * for 'breathing room' — that destroys the density that makes Linear fast."
 * Making it the comfortable variant keeps the answer to "so what" one
 * preference away rather than deleting it, and finally honours the persisted
 * density preference §5 of our own design system has promised since Phase A.
 */
import type { DemoGap } from "@/lib/demo-gaps";
import type { Density } from "@/lib/density";
import { ConfidenceMeter, ExposureCell } from "./chips";
import { SeverityGlyph, StatusGlyph } from "./glyphs";
import { age } from "@/lib/format";

export function GapRow({
  gap,
  density,
  active,
  onActivate,
  onFocus,
  rowRef,
}: {
  gap: DemoGap;
  density: Density;
  active: boolean;
  onActivate: () => void;
  onFocus: () => void;
  rowRef: (element: HTMLButtonElement | null) => void;
}) {
  const action = gap.recommendedActions[0];

  return (
    <button
      type="button"
      className="gap-row"
      // aria-current, not aria-selected: aria-selected is not valid on an
      // implicit button role, and "this is the row you are on" is what
      // aria-current means.
      aria-current={active ? "true" : undefined}
      ref={rowRef}
      onClick={onActivate}
      onFocus={onFocus}
    >
      <StatusGlyph status={gap.status} />

      {/* Mono for identity. §3: "Issue IDs and keyboard shortcuts are
          monospace; everything human-readable is Inter." */}
      <span className="gap-ref mono">{gap.reference}</span>

      <span className="gap-body">
        <span className="gap-title">{gap.title}</span>
        {density === "comfortable" && action ? (
          <span className="gap-action">
            <span className="gap-action-title">{action.title}</span>
            <span className="gap-action-rationale">{action.rationale}</span>
          </span>
        ) : null}
      </span>

      {/* The scope and the age of the newest contributing record. Not the row's
          write time — that is always now and tells nobody anything. */}
      <span className="gap-scope">{gap.scopeId}</span>
      <span className="gap-age tabular">
        {gap.dataFreshnessSeconds === null ? "age ?" : age(gap.dataFreshnessSeconds)}
      </span>

      {/* Exposure and confidence, adjacent by construction (gap-model.md §3). */}
      <span className="gap-exposure tabular">
        <ExposureCell gap={gap} />
      </span>
      <ConfidenceMeter band={gap.confidenceBand} score={gap.confidenceScore} />

      {/* §4: priority bars are "always right-aligned in the issue row before
          the assignee". */}
      <SeverityGlyph severity={gap.severity} />

      {gap.ownerInitials ? (
        <span className="avatar" aria-label={`Owner ${gap.ownerInitials}`}>
          {gap.ownerInitials}
        </span>
      ) : (
        <span className="avatar avatar-empty" aria-label="Unowned">
          <span aria-hidden="true">·</span>
        </span>
      )}
    </button>
  );
}
