"use client";

/**
 * The peek panel — Concept A's right-hand 480px sheet.
 *
 * It answers the triage question without losing list position: what was
 * observed, what was expected, what it might be worth, how confident that is,
 * and where the numbers came from. Everything else is the detail route.
 *
 * The evidence section is the part that matters most. gap-model.md §5: from a
 * gap a user must reach the metric definition and version, the source, the
 * detector version and the supporting records *without guessing how a number
 * was produced*. A peek that showed only the headline would be a prettier
 * version of the thing this product exists to replace.
 */
import { hasExposure } from "@/lib/demo-gaps";
import type { DemoGap } from "@/lib/demo-gaps";
import { ConfidenceMeter, ExposureBase, SeverityLabel, StatusLabel } from "./chips";
import { age, count, dateTime, humanise, money, ratio } from "@/lib/format";
import { TransitionControls, type TransitionRequest } from "./TransitionControls";
import type { AuditEntry } from "@/lib/ledger-state";

export function PeekPanel({
  gap,
  capabilities,
  audit,
  onAssign,
  onTransition,
  onClose,
}: {
  gap: DemoGap;
  capabilities: readonly string[];
  audit: AuditEntry[];
  onAssign: (owner: string | null) => void;
  onTransition: (request: TransitionRequest) => void;
  onClose: () => void;
}) {
  const showsExposure = hasExposure(gap);
  const basePosition =
    showsExposure && typeof gap.exposureBase === "number"
      ? gap.exposureHigh === gap.exposureLow
        ? 50
        : ((gap.exposureBase - gap.exposureLow) / (gap.exposureHigh - gap.exposureLow)) * 100
      : 50;

  return (
    <aside className="peek" aria-label={`Gap ${gap.reference}`}>
      <div className="peek-header">
        <div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 6 }}>
            <SeverityLabel severity={gap.severity} />
            <StatusLabel status={gap.status} />
            <span className="gap-ref">{gap.reference}</span>
          </div>
          <h2 className="peek-title">{gap.title}</h2>
        </div>
        <button type="button" className="peek-close" onClick={onClose} aria-label="Close peek">
          ✕
        </button>
      </div>

      <section className="peek-section">
        <p style={{ margin: 0, fontSize: "var(--text-sm)", color: "var(--fg-muted)" }}>
          {gap.summary}
        </p>
      </section>

      <section className="peek-section">
        <dl className="peek-grid">
          <dt>Observed</dt>
          <dd>{gap.observedLabel}</dd>
          <dt>Expected</dt>
          <dd>{gap.expectedLabel}</dd>
          <dt>Delta</dt>
          {/* Formatted by unit. A seconds delta rendered as a bare count reads
              as "108,000" — technically true and completely unreadable. */}
          <dd>
            {gap.unit === "ratio"
              ? `${ratio(gap.observedValue - gap.expectedValue, 1)} points`
              : gap.unit === "seconds"
                ? `${age(gap.observedValue - gap.expectedValue)} beyond expected`
                : count(gap.observedValue - gap.expectedValue)}
          </dd>
          <dt>As of</dt>
          <dd>{dateTime(gap.asOfAt)}</dd>
          <dt>Scope</dt>
          <dd>
            {gap.scopeId} <span className="mono mono-meta">({gap.scopeType})</span>
          </dd>
        </dl>
      </section>

      {showsExposure ? (
        <section className="peek-section">
          <p className="peek-label">
            {gap.isModelled ? "▨ Modelled exposure" : "Observed exposure"}
          </p>
          <div style={{ fontSize: "var(--text-sm)" }} className="tabular">
            {money(gap.exposureLow, gap.currency)}
            <div className="exposure-bar">
              <span className="exposure-base" style={{ left: `${basePosition}%` }} />
            </div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span>
                base <ExposureBase gap={gap} />
              </span>
              <span>{money(gap.exposureHigh, gap.currency)}</span>
            </div>
          </div>
          <div style={{ marginTop: 8, display: "flex", gap: 10, alignItems: "center" }}>
            <ConfidenceMeter band={gap.confidenceBand} score={gap.confidenceScore} />
            {gap.formulaLabel ? <span className="mono mono-meta">{gap.formulaLabel}</span> : null}
          </div>
          <div style={{ marginTop: 10 }}>
            {/* Every input is listed, observed ones included. "This was measured
                exactly" is as much a part of explaining a figure as "we assumed
                35%", and a figure whose inputs are not shown cannot be argued
                with — which is the same as not being trustworthy. */}
            {gap.assumptions.map((assumption) => (
              <div key={assumption.key} className="assumption">
                <b>{assumption.key}</b> · {assumption.statement}
                <div className="mono mono-meta">
                  {assumption.value} · {assumption.kind} · {assumption.source}
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : (
        <section className="peek-section">
          <p className="peek-label">Exposure</p>
          {/* Two different sentences. "This gap has no monetary figure" and
              "you may not see this gap's figure" must never read alike — the
              first is a fact about the finding, the second is a fact about you. */}
          <p style={{ margin: 0, fontSize: "var(--text-xs)", color: "var(--fg-muted)" }}>
            {gap.exposureLow === null
              ? "This gap carries no monetary figure. A late or incomplete feed is not money, and attaching a number to it would mean inventing one."
              : "Exposure is withheld from your payload. The figure exists; the fields were removed from the response before it was sent, so it never reached this page."}
          </p>
        </section>
      )}

      <section className="peek-section">
        <p className="peek-label">Confidence · {gap.confidenceBand}</p>
        <dl className="peek-grid">
          {gap.confidenceComponents.map((component) => (
            <div key={component.key} style={{ display: "contents" }}>
              <dt>{component.label}</dt>
              <dd>{component.score.toFixed(2)}</dd>
            </div>
          ))}
        </dl>
        {gap.confidenceDropped.length > 0 ? (
          <p style={{ marginTop: 8, fontSize: "var(--text-xs)", color: "var(--fg-subtle)" }}>
            {/* Dropped, not scored zero. Scoring an inapplicable component as 0
                would punish the detector for a measurement that was never
                relevant, and as 1 would reward it for the same. */}
            Not applicable, dropped and weights renormalised: {gap.confidenceDropped.join(", ")}
          </p>
        ) : null}
      </section>

      <section className="peek-section">
        <p className="peek-label">
          Evidence · {gap.evidence.length} refs ·{" "}
          {new Set(gap.evidence.map((ref) => ref.sourceLabel)).size} sources
        </p>
        {gap.evidence.map((ref) => (
          <div key={`${ref.canonicalEntity}-${ref.queryHash}`} className="evidence-item">
            <span className="grow">
              {ref.canonicalEntity}
              <div className="mono mono-meta">
                {ref.sourceLabel} · {count(ref.rowCount)} rows · {ref.sensitivity}
              </div>
            </span>
            <span className="mono mono-meta">{ref.queryHash}</span>
          </div>
        ))}
        <div className="evidence-item">
          <span className="grow">
            <div className="mono mono-meta">
              metric: {gap.metricKey} v{gap.metricVersion}
            </div>
            <div className="mono mono-meta">
              detector: {gap.ruleKey} v{gap.ruleVersion}
            </div>
          </span>
        </div>
      </section>

      <section className="peek-section">
        <p className="peek-label">Why this fired</p>
        <div className="reason-codes">
          {gap.reasonCodes.map((code) => (
            <span key={code} className="chip">
              {humanise(code)}
            </span>
          ))}
        </div>
      </section>

      <TransitionControls
        gap={gap}
        capabilities={capabilities}
        onAssign={onAssign}
        onTransition={onTransition}
      />

      {/* Every transition leaves a record. An audit row that can be absent
          while the change succeeds is an audit trail that proves nothing —
          the API writes these in the same transaction as the change. */}
      {audit.length > 0 ? (
        <section className="peek-section">
          <p className="peek-label">Audit · {audit.length}</p>
          {audit.map((entry, index) => (
            <div key={index} className="evidence-item">
              <span className="grow">
                {entry.action}
                <div className="mono mono-meta">
                  {entry.before} → {entry.after}
                  {entry.reason ? ` · ${entry.reason}` : ""}
                </div>
              </span>
              <span className="mono mono-meta">{entry.actor}</span>
            </div>
          ))}
        </section>
      ) : null}

      <section className="peek-section">
        <dl className="peek-grid">
          <dt>First seen</dt>
          <dd>{dateTime(gap.firstSeenAt)}</dd>
          <dt>Last seen</dt>
          <dd>{dateTime(gap.lastSeenAt)}</dd>
          <dt>Source age</dt>
          <dd>{gap.dataFreshnessSeconds === null ? "unknown" : age(gap.dataFreshnessSeconds)}</dd>
          <dt>Owner</dt>
          <dd>{gap.ownerInitials ?? "unassigned"}</dd>
        </dl>
      </section>
    </aside>
  );
}
