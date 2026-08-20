"use client";

/**
 * The Gap Ledger — Concept A.
 *
 * "The ledger is the application; everything else is reached from a row."
 *
 * Keyboard is the primary input, not an accessibility afterthought: triage of
 * 40 gaps is meant to be a two-minute keyboard task. J/K move, Space peeks,
 * Escape closes. The row is a real <button> inside a real list, so the keyboard
 * model and the screen-reader model are the same model.
 *
 * The flat index is precomputed rather than accumulated while mapping. A
 * counter incremented during render is a counter that double-counts under
 * StrictMode and Suspense replays — which is exactly the kind of bug that
 * appears only when the list gets long enough to matter.
 */
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import type { DemoGap, Severity } from "@/lib/demo-gaps";
import { groupBySeverity } from "@/lib/demo-gaps";
import { PeekPanel } from "./PeekPanel";
import { GapRow } from "./GapRow";
import type { Density } from "@/lib/density";
import { count, exposureRange } from "@/lib/format";
import { summarise } from "@/lib/situation";
import { ModelledMark } from "./chips";
import { SeverityGlyph } from "./glyphs";
import type { AuditEntry } from "@/lib/ledger-state";
import type { TransitionRequest } from "./TransitionControls";

interface IndexedGroup {
  severity: Severity;
  rows: { gap: DemoGap; index: number }[];
}

/**
 * The band above each severity group.
 *
 * It carries the group's own exposure envelope, not just a count. The reader is
 * deciding whether this group is worth scanning at all, and "critical · 4" does
 * not help them do that while "critical · 4 · £6,150–£12,710" does. The
 * envelope obeys the same rules as every other one on screen, because it is
 * computed by the same function — a subtotal assembled here by hand would be
 * free to sum bases and drop the confidence band.
 */
function GroupHeader({ severity, gaps }: { severity: Severity; gaps: DemoGap[] }) {
  const { exposure } = summarise(gaps);
  return (
    <h2 className={`group-header group-header-${severity}`}>
      <SeverityGlyph severity={severity} />
      <span className="group-header-word">{severity}</span>
      <span className="group-header-count tabular">{count(gaps.length)}</span>
      {exposure.kind === "range" ? (
        <span className="group-header-exposure tabular">
          {exposure.isModelled ? <ModelledMark /> : null}
          {exposureRange(exposure.low, exposure.high, exposure.currency)}
          <span className="group-header-band"> · {exposure.band} confidence</span>
        </span>
      ) : null}
      <span className="group-header-rule" aria-hidden="true" />
    </h2>
  );
}

/**
 * Presentational. It renders the gaps it is given and reports intent upward.
 *
 * It deliberately does not hold its own copy of the list. An earlier version
 * seeded `useState` from the `gaps` prop, which meant the ledger rendered a
 * snapshot taken at mount and silently ignored every filter, search and role
 * change above it — the controls moved and nothing happened. Derived state in
 * `useState` initialises once; that is the whole trap.
 */
export function GapLedger({
  gaps,
  capabilities,
  density,
  audit,
  onAssign,
  onTransition,
}: {
  gaps: DemoGap[];
  capabilities: readonly string[];
  density: Density;
  audit: Record<string, AuditEntry[]>;
  onAssign: (gapId: string, owner: string | null) => void;
  onTransition: (gapId: string, request: TransitionRequest) => void;
}) {
  const { groups, total } = useMemo(() => {
    let cursor = 0;
    const indexed: IndexedGroup[] = groupBySeverity(gaps).map((group) => ({
      severity: group.severity,
      rows: group.gaps.map((gap) => ({ gap, index: cursor++ })),
    }));
    return { groups: indexed, total: cursor };
  }, [gaps]);

  const flat = useMemo(() => groups.flatMap((group) => group.rows.map((row) => row.gap)), [groups]);

  const router = useRouter();
  const [activeIndex, setActiveIndex] = useState(0);
  const [peekOpen, setPeekOpen] = useState(false);
  const rowRefs = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    function move(delta: number) {
      setActiveIndex((current) => {
        const next = Math.max(0, Math.min(total - 1, current + delta));
        rowRefs.current[next]?.focus();
        return next;
      });
    }

    function onKeyDown(event: KeyboardEvent) {
      // Never hijack a key the user is typing into a field.
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;

      if (event.key === "j" || event.key === "ArrowDown") {
        event.preventDefault();
        move(1);
      } else if (event.key === "k" || event.key === "ArrowUp") {
        event.preventDefault();
        move(-1);
      } else if (event.key === " ") {
        event.preventDefault();
        setPeekOpen((open) => !open);
      } else if (event.key === "Enter") {
        // Enter opens the detail route; Space peeks. Concept A's keyboard model
        // separates "look without losing my place" from "go and investigate".
        const target = flat[activeIndex];
        if (target) {
          event.preventDefault();
          router.push("/gaps/" + target.id);
        }
      } else if (event.key === "Escape") {
        setPeekOpen(false);
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // Re-subscribing when the row count changes is cheap, and it keeps the
    // clamp honest without writing a ref during render.
  }, [total, flat, activeIndex, router]);

  // §8: "no gaps" (good) and "no data" (bad) must never look the same.
  if (total === 0) {
    return (
      <div className="empty">
        <p>No open gaps in this window.</p>
        <p style={{ color: "var(--fg-subtle)", fontSize: "var(--text-xs)" }}>
          Detectors ran and found nothing above threshold. This is not the same as no data — the
          sources route shows what reported.
        </p>
      </div>
    );
  }

  // A dismissal shortens the list, so the cursor can point past the end.
  const active = flat[Math.min(activeIndex, flat.length - 1)];

  return (
    <>
      <div>
        {groups.map((group) => (
          <section key={group.severity} aria-label={`${group.severity} severity`}>
            <GroupHeader severity={group.severity} gaps={group.rows.map((row) => row.gap)} />
            <ul className="gap-list">
              {group.rows.map(({ gap, index }) => (
                <li key={gap.id}>
                  <GapRow
                    gap={gap}
                    density={density}
                    active={index === activeIndex}
                    onActivate={() => {
                      setActiveIndex(index);
                      setPeekOpen(true);
                    }}
                    onFocus={() => setActiveIndex(index)}
                    rowRef={(element) => {
                      rowRefs.current[index] = element;
                    }}
                  />
                </li>
              ))}
            </ul>
          </section>
        ))}
        <p className="keyboard-hint">
          <kbd>J</kbd> <kbd>K</kbd> move · <kbd>Space</kbd> peek · <kbd>Enter</kbd> open ·{" "}
          <kbd>Esc</kbd> close. Assign and status live in the peek.
        </p>
      </div>
      {peekOpen && active ? (
        <PeekPanel
          gap={active}
          capabilities={capabilities}
          audit={audit[active.id] ?? []}
          onAssign={(owner) => onAssign(active.id, owner)}
          onTransition={(request) => onTransition(active.id, request)}
          onClose={() => setPeekOpen(false)}
        />
      ) : null}
    </>
  );
}
