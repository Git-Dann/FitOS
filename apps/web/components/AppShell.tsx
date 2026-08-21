/**
 * The application shell — nav rail, top bar, demo banner.
 *
 * Routes that do not exist yet are rendered as disabled items rather than
 * links. CLAUDE.md forbids placeholder buttons on a route marked complete, and
 * a nav item that looks live and goes nowhere is exactly that. Showing the
 * shape of the product while being honest about what is built is the compromise
 * this makes.
 */
import Link from "next/link";
import type { ReactNode } from "react";
import { ThemeToggle } from "./ThemeToggle";

interface NavEntry {
  label: string;
  glyph: string;
  count?: number;
  href?: string;
  current?: boolean;
}

const PRIMARY: NavEntry[] = [
  { label: "Operations", glyph: "◎", href: "/" },
  { label: "Inbox", glyph: "⌂", href: "/inbox" },
  { label: "Gaps", glyph: "⚑" },
  { label: "Explore", glyph: "⌕" },
  { label: "Metrics", glyph: "∑", href: "/metrics" },
  { label: "Sources", glyph: "⇄", href: "/sources" },
  { label: "Playbooks", glyph: "▤" },
  { label: "Outcomes", glyph: "✓" },
];

function NavItem({ entry }: { entry: NavEntry }) {
  const content = (
    <>
      <span className="nav-item-main">
        <span className="nav-glyph" aria-hidden="true">
          {entry.glyph}
        </span>
        <span className="nav-label">{entry.label}</span>
      </span>
      {entry.count !== undefined ? <span className="nav-count">{entry.count}</span> : null}
    </>
  );

  if (!entry.href) {
    return (
      <button type="button" className="nav-item" disabled title="Arrives later in Phase E">
        {content}
      </button>
    );
  }
  return (
    <Link className="nav-item" href={entry.href} aria-current={entry.current ? "page" : undefined}>
      {content}
    </Link>
  );
}

export function AppShell({
  className,
  title,
  meta,
  current = "/",
  inboxCount,
  demoNote = "Every gap below is fictional.",
  children,
}: {
  title: string;
  meta: string;
  current?: string;
  /** Scopes the density preference, so the rows and the switch cannot disagree. */
  className?: string;
  /**
   * The live open-gap count, or undefined on a route that does not know it.
   *
   * It is a prop rather than a constant because it used to be a constant: the
   * nav read `8` and the route title read `8 open` while seven rows were on
   * screen after a dismissal. Three counters, one of them derived from the
   * actual list. A count nobody derives is a count that goes stale silently,
   * which is the "no fake status" rule in miniature.
   */
  inboxCount?: number;
  /** What is fictional on *this* route. A banner that says "every gap below"
   *  on a page with no gaps is a banner people learn to stop reading. */
  demoNote?: string;
  children: ReactNode;
}) {
  return (
    <div className={className ? `shell ${className}` : "shell"}>
      <nav className="nav" aria-label="Primary">
        <div className="nav-brand">
          <span className="nav-mark" aria-hidden="true">
            F
          </span>
          <span>Northstar</span>
        </div>
        {PRIMARY.map((entry) => (
          <NavItem
            key={entry.label}
            entry={{
              ...entry,
              current: entry.href === current,
              ...(entry.label === "Inbox" && inboxCount !== undefined ? { count: inboxCount } : {}),
            }}
          />
        ))}
      </nav>

      <main>
        <div className="topbar">
          <h1>{title}</h1>
          <span className="topbar-spacer" />
          <span className="topbar-meta">{meta}</span>
          <ThemeToggle />
        </div>

        {/* product-spec.md §8: demo data is labelled on every surface where it
            appears, including screenshots. Not dismissible, for that reason —
            but one line, with the rest behind a disclosure. Three lines of
            preamble above the fold is how a banner teaches people to skip it,
            and on a 390px viewport it was taking 90px of an 844px screen. */}
        <details className="demo-banner">
          <summary>
            <span aria-hidden="true">▨</span> <strong>Demonstration data</strong> · {demoNote}
          </summary>
          <p>
            The detectors, exposure model and confidence model that shape these rows are real and
            tested. The readings they ran against are not: no figure here describes a real store,
            campaign or customer.
          </p>
        </details>

        {children}
      </main>
    </div>
  );
}
