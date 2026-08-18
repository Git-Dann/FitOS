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

interface NavEntry {
  label: string;
  glyph: string;
  count?: number;
  href?: string;
  current?: boolean;
}

const PRIMARY: NavEntry[] = [
  { label: "Inbox", glyph: "⌂", count: 8, href: "/" },
  { label: "Gaps", glyph: "⚑" },
  { label: "Explore", glyph: "⌕" },
  { label: "Metrics", glyph: "∑", href: "/metrics" },
  { label: "Sources", glyph: "⇄", href: "/sources" },
  { label: "Playbooks", glyph: "▤" },
  { label: "Outcomes", glyph: "✓" },
];

const VIEWS: NavEntry[] = [
  { label: "Mine", glyph: "★" },
  { label: "Stale", glyph: "★" },
  { label: "Unowned", glyph: "★" },
];

function NavItem({ entry }: { entry: NavEntry }) {
  const content = (
    <>
      <span>
        <span aria-hidden="true" style={{ marginRight: 8 }}>
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
  title,
  meta,
  current = "/",
  demoNote = "Every gap below is fictional.",
  children,
}: {
  title: string;
  meta: string;
  current?: string;
  /** What is fictional on *this* route. A banner that says "every gap below"
   *  on a page with no gaps is a banner people learn to stop reading. */
  demoNote?: string;
  children: ReactNode;
}) {
  return (
    <div className="shell">
      <nav className="nav" aria-label="Primary">
        <div className="nav-brand">
          <span className="nav-mark" aria-hidden="true">
            F
          </span>
          <span>Northstar</span>
        </div>
        {PRIMARY.map((entry) => (
          <NavItem key={entry.label} entry={{ ...entry, current: entry.href === current }} />
        ))}
        <div className="nav-section">Views</div>
        {VIEWS.map((entry) => (
          <NavItem key={entry.label} entry={entry} />
        ))}
      </nav>

      <main>
        <div className="topbar">
          <h1>{title}</h1>
          <span className="topbar-spacer" />
          <span className="topbar-meta">{meta}</span>
        </div>

        {/* product-spec.md §8: demo data is labelled on every surface where it
            appears, including screenshots. Not dismissible, for that reason. */}
        <div className="demo-banner">
          <span aria-hidden="true">▨</span>
          <span>
            <strong>Demonstration data.</strong> {demoNote} The detectors, exposure and confidence
            models that shape these rows are real and tested; the readings they ran against are not.
          </span>
        </div>

        {children}
      </main>
    </div>
  );
}
