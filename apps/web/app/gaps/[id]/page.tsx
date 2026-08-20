import { notFound } from "next/navigation";
import Link from "next/link";
import { AppShell } from "@/components/AppShell";
import { ConfidenceMeter, SeverityLabel, StatusLabel } from "@/components/chips";
import { DEMO_GAPS, hasExposure } from "@/lib/demo-gaps";
import { age, count, dateTime, humanise, money, ratio } from "@/lib/format";

/**
 * Gap detail — the evidence route.
 *
 * The peek answers "should I act on this". This answers "how was this number
 * produced", which gap-model.md §5 says a user must be able to reach *without
 * guessing*: the metric definition and version, the source connection, the
 * detector version and the supporting records.
 *
 * Exposure is rendered from the seeded payload here rather than the
 * role-filtered one, because this route has no client boundary and no role
 * switcher. That is a real limitation of the demonstration and is stated on the
 * page — the API filters per request, and a static route cannot.
 */
export function generateStaticParams() {
  return DEMO_GAPS.map((gap) => ({ id: gap.id }));
}

export default async function GapDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const gap = DEMO_GAPS.find((candidate) => candidate.id === id);
  if (!gap) notFound();

  return (
    <AppShell title={gap.reference} meta={`as of ${dateTime(gap.asOfAt)}`}>
      <div className="route-body">
        <Link className="back-link" href="/">
          ← Back to the inbox
        </Link>

        <div className="detail-head">
          <SeverityLabel severity={gap.severity} />
          <StatusLabel status={gap.status} />
          <ConfidenceMeter band={gap.confidenceBand} score={gap.confidenceScore} />
          <span className="chip">{gap.gapTypeLabel}</span>
        </div>
        <h2 className="detail-title">{gap.title}</h2>
        <p className="detail-summary">{gap.summary}</p>

        <div className="detail-grid">
          <section className="detail-pane">
            <p className="peek-label">The comparison</p>
            <dl className="peek-grid">
              <dt>Observed</dt>
              <dd>{gap.observedLabel}</dd>
              <dt>Expected</dt>
              <dd>{gap.expectedLabel}</dd>
              <dt>Delta</dt>
              <dd>
                {gap.unit === "ratio"
                  ? `${ratio(gap.observedValue - gap.expectedValue, 1)} points`
                  : gap.unit === "seconds"
                    ? `${age(gap.observedValue - gap.expectedValue)} beyond expected`
                    : count(gap.observedValue - gap.expectedValue)}
              </dd>
              <dt>Scope</dt>
              <dd>
                {gap.scopeId} <span className="mono">({gap.scopeType})</span>
              </dd>
              <dt>Window</dt>
              <dd className="tabular">
                {dateTime(gap.firstSeenAt)} → {dateTime(gap.asOfAt)}
              </dd>
              <dt>Source age</dt>
              <dd className="tabular">
                {gap.dataFreshnessSeconds === null ? "unknown" : age(gap.dataFreshnessSeconds)}
              </dd>
            </dl>
          </section>

          <section className="detail-pane">
            <p className="peek-label">Reproducibility</p>
            {/* The triple that makes a gap re-derivable years later. A gap that
                cannot name the metric version, the detector version and the
                as-of time is not evidence, it is an opinion with a timestamp. */}
            <dl className="peek-grid">
              <dt>Metric</dt>
              <dd className="mono">
                {gap.metricKey} v{gap.metricVersion}
              </dd>
              <dt>Detector</dt>
              <dd className="mono">
                {gap.ruleKey} v{gap.ruleVersion}
              </dd>
              <dt>As of</dt>
              <dd className="tabular">{dateTime(gap.asOfAt)}</dd>
              <dt>Pack</dt>
              <dd className="mono">{gap.packKey}</dd>
            </dl>
            <div className="reason-codes" style={{ marginTop: 10 }}>
              {gap.reasonCodes.map((code) => (
                <span key={code} className="chip">
                  {humanise(code)}
                </span>
              ))}
            </div>
          </section>

          <section className="detail-pane detail-wide">
            <p className="peek-label">Evidence · {gap.evidence.length}</p>
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Canonical entity</th>
                  <th scope="col">Source</th>
                  <th scope="col">Metric</th>
                  <th scope="col">Rows</th>
                  <th scope="col">Sensitivity</th>
                  <th scope="col">Query hash</th>
                </tr>
              </thead>
              <tbody>
                {gap.evidence.map((ref) => (
                  <tr key={`${ref.canonicalEntity}-${ref.queryHash}`}>
                    <th scope="row" className="mono">
                      {ref.canonicalEntity}
                    </th>
                    <td>{ref.sourceLabel}</td>
                    <td className="mono">
                      {ref.metricKey} v{ref.metricVersion}
                    </td>
                    <td className="tabular">{count(ref.rowCount)}</td>
                    <td>{ref.sensitivity}</td>
                    <td className="mono">{ref.queryHash}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          {hasExposure(gap) ? (
            <section className="detail-pane detail-wide">
              <p className="peek-label">
                {gap.isModelled ? "▨ Modelled exposure" : "Observed exposure"} ·{" "}
                {gap.confidenceBand} confidence
              </p>
              <p className="detail-figure tabular">
                {money(gap.exposureLow, gap.currency)} – {money(gap.exposureHigh, gap.currency)}
                {typeof gap.exposureBase === "number" ? (
                  <span className="detail-base"> base {money(gap.exposureBase, gap.currency)}</span>
                ) : null}
              </p>
              {gap.formulaLabel ? <p className="mono">{gap.formulaLabel}</p> : null}
              {gap.assumptions.map((assumption) => (
                <div key={assumption.key} className="assumption">
                  <b>{assumption.key}</b> · {assumption.statement}
                  <div className="mono">
                    {assumption.value} · {assumption.kind} · {assumption.source}
                  </div>
                </div>
              ))}
              <p className="action-note" style={{ marginTop: 10 }}>
                This route renders the seeded payload. The API filters exposure per request from the
                caller&rsquo;s capabilities; a statically rendered page cannot, so the role switcher
                on the inbox does not apply here.
              </p>
            </section>
          ) : null}

          <section className="detail-pane detail-wide">
            <p className="peek-label">Confidence breakdown</p>
            <dl className="peek-grid">
              {gap.confidenceComponents.map((component) => (
                <div key={component.key} style={{ display: "contents" }}>
                  <dt>{component.label}</dt>
                  <dd className="tabular">{component.score.toFixed(2)}</dd>
                </div>
              ))}
              <dt>Score</dt>
              <dd className="tabular">{gap.confidenceScore.toFixed(3)}</dd>
            </dl>
            {gap.confidenceDropped.length > 0 ? (
              <p className="action-note" style={{ marginTop: 8 }}>
                Dropped as not applicable, with the weights renormalised over what remains:{" "}
                {gap.confidenceDropped.join(", ")}. Scoring an inapplicable component as zero would
                punish the detector for a measurement that was never relevant; scoring it as one
                would reward it for the same.
              </p>
            ) : null}
          </section>
        </div>
      </div>
    </AppShell>
  );
}
