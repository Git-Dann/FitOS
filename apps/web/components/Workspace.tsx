"use client";

/**
 * The workspace — role, views, search and the ledger, in one client boundary.
 *
 * Role lives here rather than in a context provider because it changes what the
 * *data layer* returns, not just what the tree renders. Switching to frontline
 * re-derives the gap list with exposure stripped, exactly as a different token
 * would produce a different payload from the API. Keeping that at the top makes
 * it obvious that no component is deciding what to hide.
 */
import { useMemo, useState } from "react";
import type { DemoGap, Severity } from "@/lib/demo-gaps";
import { DEMO_AS_OF } from "@/lib/demo-gaps";
import { STALE_SECONDS, summarise } from "@/lib/situation";
import { SituationStrip } from "./SituationStrip";
import { count, dateTime } from "@/lib/format";
import { ROLES, ROLE_CAPABILITIES, type Role, withheldForCapabilities } from "@/lib/roles";
import { ACTOR, assign, transition, type LedgerState } from "@/lib/ledger-state";
import type { TransitionRequest } from "./TransitionControls";
import type { GapStatus } from "@fitos/contracts/lifecycle";
import { GapLedger } from "./GapLedger";
import { AppShell } from "./AppShell";
import { DEMO_SOURCES } from "@/lib/demo-sources";

export type ViewKey = "all" | "mine" | "stale" | "unowned";

const VIEWS: { key: ViewKey; label: string; describe: string }[] = [
  { key: "all", label: "All open", describe: "Every gap that is not resolved or dismissed" },
  { key: "mine", label: "Mine", describe: `Assigned to ${ACTOR}` },
  { key: "stale", label: "Stale", describe: "Source data older than 6 hours" },
  { key: "unowned", label: "Unowned", describe: "Nobody has picked these up" },
];

function applyView(gaps: DemoGap[], view: ViewKey): DemoGap[] {
  switch (view) {
    case "mine":
      return gaps.filter((gap) => gap.ownerInitials === ACTOR);
    case "unowned":
      return gaps.filter((gap) => gap.ownerInitials === null);
    case "stale":
      // Unknown age counts as stale. A source whose recency cannot be
      // established is not a fresh source, and the flattering reading is the
      // one that hides the problem.
      return gaps.filter(
        (gap) => gap.dataFreshnessSeconds === null || gap.dataFreshnessSeconds > STALE_SECONDS,
      );
    default:
      return gaps;
  }
}

function applySearch(gaps: DemoGap[], query: string): DemoGap[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return gaps;
  return gaps.filter((gap) =>
    [gap.title, gap.reference, gap.scopeId, gap.gapTypeLabel, gap.summary]
      .join(" ")
      .toLowerCase()
      .includes(needle),
  );
}

export function Workspace({ gaps }: { gaps: DemoGap[] }) {
  const [role, setRole] = useState<Role>("manager");
  const [view, setView] = useState<ViewKey>("all");
  const [query, setQuery] = useState("");
  const [severity, setSeverity] = useState<Severity | null>(null);
  const [state, setState] = useState<LedgerState>({ gaps, audit: {} });

  const capabilities = ROLE_CAPABILITIES[role];

  // Terminal gaps leave the inbox, which is what makes dismissal feel like the
  // consequential act it is. They are not deleted — the gaps route shows them.
  const open = useMemo(
    () => state.gaps.filter((gap) => gap.status !== "resolved" && gap.status !== "dismissed"),
    [state.gaps],
  );

  // The payload the caller would actually receive. Exposure is removed here,
  // at the boundary, never in a component that chose not to draw it.
  const visible = useMemo(() => withheldForCapabilities(open, capabilities), [open, capabilities]);

  // The strip summarises what the *view* holds, before the severity pill and
  // the search box narrow it further. Recomputing it from the filtered list
  // would make the counts change as you click them, which is the one thing an
  // orientation layer must not do.
  const summary = useMemo(() => summarise(applyView(visible, view)), [visible, view]);

  const filtered = useMemo(() => {
    const inView = applyView(visible, view);
    const bySeverity = severity ? inView.filter((gap) => gap.severity === severity) : inView;
    return applySearch(bySeverity, query);
  }, [visible, view, query, severity]);

  const activeView = VIEWS.find((entry) => entry.key === view);

  // One count, derived from the list that is actually on screen. The nav badge,
  // the route title and the ledger cannot disagree because there is nothing for
  // them to disagree about.
  const staleSources = DEMO_SOURCES.filter(
    (source) => source.state !== "healthy" && source.state !== "fixture",
  ).length;

  return (
    <AppShell
      title="Inbox"
      inboxCount={visible.length}
      meta={`as of ${dateTime(DEMO_AS_OF)} · ${count(DEMO_SOURCES.length)} sources · ${count(staleSources)} not healthy`}
    >
      <SituationStrip
        summary={summary}
        asOfLabel={dateTime(DEMO_AS_OF)}
        activeSeverity={severity}
        onSeverity={setSeverity}
      />

      <div className="toolbar">
        <label className="visually-hidden" htmlFor="role">
          Role
        </label>
        <select
          id="role"
          className="control"
          value={role}
          onChange={(event) => setRole(event.target.value as Role)}
          title="Switch role. Exposure is withheld from a frontline payload server-side."
        >
          {ROLES.map((entry) => (
            <option key={entry} value={entry}>
              {entry}
            </option>
          ))}
        </select>

        <div className="view-tabs" role="tablist" aria-label="Saved views">
          {VIEWS.map((entry) => (
            <button
              key={entry.key}
              type="button"
              role="tab"
              aria-selected={view === entry.key}
              className="view-tab"
              onClick={() => setView(entry.key)}
              title={entry.describe}
            >
              {entry.label}
            </button>
          ))}
        </div>

        <input
          className="control search"
          type="search"
          value={query}
          placeholder="Search title, scope or reference"
          aria-label="Search gaps"
          onChange={(event) => setQuery(event.target.value)}
        />

        {severity ? (
          <button type="button" className="filter-clear" onClick={() => setSeverity(null)}>
            {severity} only <span aria-hidden="true">✕</span>
          </button>
        ) : null}

        <span className="topbar-spacer" />
        <span className="toolbar-count tabular">
          {count(filtered.length)} of {count(visible.length)}
        </span>
      </div>

      {/* Saying what is being withheld, rather than silently showing less.
          A frontline caller should know a figure exists and is not theirs to
          see — that is a different thing from the figure not existing. */}
      {!capabilities.includes("gap.view_exposure") ? (
        <div className="withheld-banner">
          Exposure is withheld from a <strong>{role}</strong> payload. The fields are absent from
          the response, not hidden here — masking client-side would mean the number had already
          crossed the wire.
        </div>
      ) : null}

      {filtered.length === 0 && visible.length > 0 ? (
        <div className="empty">
          <p>
            Nothing matches {activeView?.label.toLowerCase()}
            {severity ? ` and ${severity} severity` : ""}
            {query ? ` and “${query}”` : ""}.
          </p>
          <p style={{ color: "var(--fg-subtle)", fontSize: "var(--text-xs)" }}>
            {count(visible.length)} gaps are open outside this filter. This is a filter result, not
            an empty ledger.
          </p>
        </div>
      ) : (
        <GapLedger
          gaps={filtered}
          capabilities={capabilities}
          audit={state.audit}
          onAssign={(gapId, owner) => setState((current) => assign(current, gapId, owner))}
          onTransition={(gapId, request: TransitionRequest) =>
            setState((current) =>
              transition(current, gapId, request as { to: GapStatus }, capabilities),
            )
          }
        />
      )}
    </AppShell>
  );
}
