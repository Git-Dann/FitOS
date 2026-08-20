/**
 * The drawn glyph set: gap status and gap severity.
 *
 * From DESIGN.md §4, Status Icon Set: "16pt vector glyphs **drawn, not emoji**:
 * dashed circle (backlog), thin ring (todo), half-pie (in progress), purple
 * ring (in review), check-fill (done), cross-fill (canceled)". And from §7,
 * twice over: "Use the iconographic status system (drawn glyphs) instead of
 * colored fills or text badges" / "Don't use colored status badges with text —
 * the drawn icon system *is* the language."
 *
 * That replaces the chip-with-a-word treatment the ledger used to carry, which
 * matters for more than fashion: a chip spends 60px of row width restating what
 * a 16px glyph says, and the row is the component 90% of the pixels go to.
 *
 * Both sets stay legible without colour, which is the §9 requirement our own
 * design system imposes on top of the source spec. Status is distinguished by
 * *shape* — how much of the ring is filled — and severity by *bar count*, so
 * neither depends on hue. The source spec happens to agree: only Urgent is
 * coloured, and High/Medium/Low are all `#8A8F98`, differing by how many bars
 * are filled.
 */
import type { GapStatus, Severity } from "@/lib/demo-gaps";

const SIZE = 16;

/** Where each status sits on the "how far through the work" arc, 0 to 1. */
const STATUS_PROGRESS: Record<GapStatus, number> = {
  detected: 0,
  triaged: 0,
  investigating: 0.5,
  actioned: 0.75,
  validating: 0.9,
  resolved: 1,
  dismissed: 0,
};

const STATUS_LABEL: Record<GapStatus, string> = {
  detected: "Detected — no one has looked at this yet",
  triaged: "Triaged — accepted as real, not started",
  investigating: "Investigating — actively being worked",
  actioned: "Actioned — a change was made, the window is open",
  validating: "Validating — measuring whether the action worked",
  resolved: "Resolved — the outcome closed it",
  dismissed: "Dismissed — judged not worth acting on",
};

/**
 * A pie wedge from 12 o'clock, clockwise. Returned as a path so the glyph
 * animates between states as a shape change rather than a colour change —
 * §6 Motion: "150ms glyph morph between status icons".
 */
function wedge(fraction: number, radius: number): string {
  const centre = SIZE / 2;
  if (fraction >= 1)
    return `M ${centre} ${centre} m -${radius} 0 a ${radius} ${radius} 0 1 0 ${radius * 2} 0 a ${radius} ${radius} 0 1 0 -${radius * 2} 0`;
  const angle = fraction * 2 * Math.PI - Math.PI / 2;
  const x = centre + radius * Math.cos(angle);
  const y = centre + radius * Math.sin(angle);
  const large = fraction > 0.5 ? 1 : 0;
  return `M ${centre} ${centre} L ${centre} ${centre - radius} A ${radius} ${radius} 0 ${large} 1 ${x} ${y} Z`;
}

export function StatusGlyph({ status }: { status: GapStatus }) {
  const progress = STATUS_PROGRESS[status];
  const centre = SIZE / 2;

  return (
    <svg
      className={`glyph glyph-status glyph-status-${status}`}
      width={SIZE}
      height={SIZE}
      viewBox={`0 0 ${SIZE} ${SIZE}`}
      role="img"
      aria-label={STATUS_LABEL[status]}
    >
      {/* Detected is a dashed ring — the source spec's "backlog" state, which
          reads as "nobody has picked this up" without needing a word. */}
      <circle
        cx={centre}
        cy={centre}
        r={6}
        fill="none"
        strokeWidth={1.5}
        strokeDasharray={status === "detected" ? "2.2 2.2" : undefined}
      />
      {progress > 0 && progress < 1 ? <path d={wedge(progress, 4)} stroke="none" /> : null}
      {status === "resolved" ? (
        <>
          <circle cx={centre} cy={centre} r={6} stroke="none" />
          <path
            d="M 5 8.2 L 7.2 10.4 L 11.2 5.9"
            fill="none"
            strokeWidth={1.6}
            strokeLinecap="round"
            strokeLinejoin="round"
            className="glyph-knockout"
          />
        </>
      ) : null}
      {status === "dismissed" ? (
        <>
          <circle cx={centre} cy={centre} r={6} stroke="none" />
          <path
            d="M 5.8 5.8 L 10.2 10.2 M 10.2 5.8 L 5.8 10.2"
            fill="none"
            strokeWidth={1.6}
            strokeLinecap="round"
            className="glyph-knockout"
          />
        </>
      ) : null}
    </svg>
  );
}

/** How many of the three bars are filled. Critical is the urgent glyph instead. */
const SEVERITY_BARS: Record<Severity, number> = {
  critical: 3,
  high: 3,
  medium: 2,
  low: 1,
  info: 0,
};

const SEVERITY_LABEL: Record<Severity, string> = {
  critical: "Critical severity",
  high: "High severity",
  medium: "Medium severity",
  low: "Low severity",
  info: "Informational",
};

/**
 * §4 Priority Bars: "A 14pt-wide glyph of three ascending bars. Urgent renders
 * as a filled amber/red square with `!`; High = 3 filled, Medium = 2, Low = 1,
 * None = 3 dimmed. Always right-aligned in the issue row before the assignee."
 *
 * Severity maps onto this cleanly, and the mapping is the reason the ledger no
 * longer needs a coloured chip *or* the severity rail that preceded it: bar
 * count survives greyscale, and only critical takes a colour.
 */
export function SeverityGlyph({ severity }: { severity: Severity }) {
  const filled = SEVERITY_BARS[severity];

  if (severity === "critical") {
    return (
      <svg
        className="glyph glyph-severity glyph-urgent"
        width={14}
        height={14}
        viewBox="0 0 14 14"
        role="img"
        aria-label={SEVERITY_LABEL[severity]}
      >
        <rect x="0.5" y="0.5" width="13" height="13" rx="3" stroke="none" />
        <path
          d="M 7 3.4 L 7 8 M 7 10.1 L 7 10.9"
          fill="none"
          strokeWidth={1.7}
          strokeLinecap="round"
          className="glyph-knockout"
        />
      </svg>
    );
  }

  return (
    <svg
      className="glyph glyph-severity"
      width={14}
      height={14}
      viewBox="0 0 14 14"
      role="img"
      aria-label={SEVERITY_LABEL[severity]}
    >
      {[0, 1, 2].map((index) => (
        <rect
          key={index}
          x={1 + index * 4.5}
          y={10 - index * 3}
          width={3}
          height={3 + index * 3}
          rx={1}
          stroke="none"
          className={index < filled ? "bar-on" : "bar-off"}
        />
      ))}
    </svg>
  );
}
