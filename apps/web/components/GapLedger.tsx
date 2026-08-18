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
import { ConfidenceMeter, ExposureCell, SeverityChip, StatusChip } from "./chips";
import { PeekPanel } from "./PeekPanel";
import { age, shortDate } from "@/lib/format";
import type { AuditEntry } from "@/lib/ledger-state";
import type { TransitionRequest } from "./TransitionControls";

interface IndexedGroup {
  severity: Severity;
  rows: { gap: DemoGap; index: number }[];
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
  audit,
  onAssign,
  onTransition,
}: {
  gaps: DemoGap[];
  capabilities: readonly string[];
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
            <h2 className="group-header">
              {group.severity} · {group.rows.length}
            </h2>
            <ul className="gap-list">
              {group.rows.map(({ gap, index }) => (
                <li key={gap.id}>
                  <button
                    type="button"
                    className="gap-row"
                    // aria-current, not aria-selected: aria-selected is not
                    // valid on an implicit button role, and "this is the row
                    // you are on" is what aria-current means.
                    aria-current={index === activeIndex ? "true" : undefined}
                    ref={(element) => {
                      rowRefs.current[index] = element;
                    }}
                    onClick={() => {
                      setActiveIndex(index);
                      setPeekOpen(true);
                    }}
                    onFocus={() => setActiveIndex(index)}
                  >
                    <span className="gap-row-top">
                      <SeverityChip severity={gap.severity} />
                      <span className="gap-title">{gap.title}</span>
                      <span className="gap-ref">{gap.reference}</span>
                    </span>
                    <span className="gap-row-meta tabular">
                      <span className="gap-scope">{gap.gapTypeLabel}</span>
                      <span className="gap-scope">{gap.scopeId}</span>
                      {/* Exposure and confidence are adjacent by construction —
                          see design-concepts.md, information hierarchy. */}
                      <ExposureCell gap={gap} />
                      <ConfidenceMeter band={gap.confidenceBand} score={gap.confidenceScore} />
                      {/* The age of the newest contributing source record, not
                          the row's write time. "How old is what this is based
                          on" is the triage question; the write time is always
                          now and tells nobody anything. */}
                      <span>
                        {gap.dataFreshnessSeconds === null
                          ? "age unknown"
                          : `${age(gap.dataFreshnessSeconds)} old`}
                      </span>
                      <StatusChip status={gap.status} />
                      <span>{gap.ownerInitials ?? "—"}</span>
                      <span className="gap-scope">1st: {shortDate(gap.firstSeenAt)}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
        <p className="keyboard-hint">
          <kbd>J</kbd> <kbd>K</kbd> move · <kbd>Space</kbd> peek · <kbd>Esc</kbd> close. Assign and
          status live in the peek. Bulk select, the command menu and the detail route arrive with
          the rest of Phase E.
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
