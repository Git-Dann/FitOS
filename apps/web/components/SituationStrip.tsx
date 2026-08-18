/**
 * The orientation band above the ledger.
 *
 * The inbox used to open straight onto rows, which answers "which one next"
 * without ever answering "how bad is this". That is the wrong order: nobody
 * triages before they have a sense of scale. design-concepts.md names this as
 * Concept A's own weakness — "it is weakest at 'what is happening in my store
 * right now', which is the manager's actual first question".
 *
 * What it is *not* is a row of giant metric cards. design-system.md §4 forbids
 * those by name, and §2 reserves accent for interaction, so nothing here is
 * coloured to look urgent. The strip is dense, hairline-separated and reads as
 * one sentence: this many gaps, this much exposure, this old, this many
 * unowned. The severity counts are the filter control, not decoration.
 *
 * The exposure figure is the sellable number and also the most dangerous one,
 * so every qualification travels with it rather than being available on hover:
 * it is a range not a point, it names the weakest confidence band it contains,
 * it says how many gaps were left out and why, and it says "estimated
 * exposure" because gap-model.md §3 forbids calling it a saving.
 */
import type { Severity } from "@/lib/demo-gaps";
import { STALE_SECONDS, type SituationSummary } from "@/lib/situation";
import { age, count, exposureRange } from "@/lib/format";
import { ModelledKey, ModelledMark } from "./chips";

const SEVERITY_GLYPH: Record<Severity, string> = {
  critical: "▲",
  high: "●",
  medium: "◆",
  low: "▪",
  info: "·",
};

/** The exposure block, with its qualifications inline rather than on hover. */
function Exposure({ summary }: { summary: SituationSummary }) {
  const { exposure } = summary;

  if (exposure.kind === "withheld") {
    return (
      <div className="situation-figure">
        <p className="situation-label">Estimated exposure</p>
        <p className="situation-value situation-value-absent">withheld</p>
        <p className="situation-note">
          Exposure fields are absent from this payload. A figure exists; it is not yours to see.
        </p>
      </div>
    );
  }

  if (exposure.kind === "none") {
    return (
      <div className="situation-figure">
        <p className="situation-label">Estimated exposure</p>
        <p className="situation-value situation-value-absent">none priced</p>
        <p className="situation-note">
          Nothing in view carries a monetary figure. Attaching one would mean inventing it.
        </p>
      </div>
    );
  }

  if (exposure.kind === "mixed") {
    return (
      <div className="situation-figure">
        <p className="situation-label">Estimated exposure</p>
        <p className="situation-value situation-value-absent">not summable</p>
        <p className="situation-note">
          Gaps in view price in {exposure.currencies.join(" and ")}. There is no rate in the gap
          record, so these are not added.
        </p>
      </div>
    );
  }

  const excluded: string[] = [];
  if (exposure.excludedLowConfidence > 0) {
    excluded.push(`${count(exposure.excludedLowConfidence)} low-confidence excluded`);
  }
  if (exposure.withoutExposure > 0) {
    excluded.push(`${count(exposure.withoutExposure)} carry no money`);
  }

  return (
    <div className="situation-figure">
      <p className="situation-label">Estimated exposure · not a saving</p>
      <p className="situation-value tabular">
        {exposure.isModelled ? <ModelledMark /> : null}
        {exposureRange(exposure.low, exposure.high, exposure.currency)}
      </p>
      {/* §3: exposure never appears without its confidence band adjacent. On an
          aggregate that means the weakest band it contains, not an average. */}
      <p className="situation-note">
        Range across {count(exposure.contributing)} gaps, weakest band{" "}
        <strong>{exposure.band}</strong>
        {excluded.length > 0 ? ` · ${excluded.join(" · ")}` : ""}
      </p>
      {exposure.isModelled ? <ModelledKey /> : null}
    </div>
  );
}

export function SituationStrip({
  summary,
  asOfLabel,
  activeSeverity,
  onSeverity,
}: {
  summary: SituationSummary;
  asOfLabel: string;
  activeSeverity: Severity | null;
  onSeverity: (severity: Severity | null) => void;
}) {
  // Stale and age-unknown are counted together here and named separately
  // below. "We know it is old" and "we cannot tell how old it is" are both
  // reasons to distrust a figure, and neither is a reason to hide it.
  const untrusted = summary.stale + summary.ageUnknown;

  return (
    <section className="situation" aria-label="Situation summary">
      <div className="situation-figure">
        <p className="situation-label">Open gaps · as of {asOfLabel}</p>
        <p className="situation-value tabular">{count(summary.total)}</p>
        <div className="situation-severities" role="group" aria-label="Filter by severity">
          {summary.bySeverity.map((entry) => (
            <button
              key={entry.severity}
              type="button"
              className={`sev-pill sev-pill-${entry.severity}`}
              aria-pressed={activeSeverity === entry.severity}
              onClick={() => onSeverity(activeSeverity === entry.severity ? null : entry.severity)}
              title={`Show only ${entry.severity} gaps`}
            >
              <span aria-hidden="true">{SEVERITY_GLYPH[entry.severity]}</span>
              <span className="tabular">{count(entry.count)}</span>
              <span className="sev-pill-word">{entry.severity}</span>
            </button>
          ))}
        </div>
      </div>

      <Exposure summary={summary} />

      <div className="situation-figure">
        <p className="situation-label">Standing on stale input</p>
        <p className="situation-value tabular">
          {count(untrusted)}
          <span className="situation-value-unit"> of {count(summary.total)}</span>
        </p>
        <p className="situation-note">
          {untrusted === 0
            ? `Every gap in view is computed on data newer than ${age(STALE_SECONDS)}.`
            : `${count(summary.stale)} older than ${age(STALE_SECONDS)}`}
          {summary.ageUnknown > 0 ? ` · ${count(summary.ageUnknown)} age unknown` : ""}
          {" · "}
          {count(summary.unowned)} unowned
        </p>
      </div>
    </section>
  );
}
