import { AppShell } from "@/components/AppShell";
import catalogue from "@fitos/contracts/metric-catalogue.json";
import { humanise } from "@/lib/format";

/**
 * Metrics — the governed catalogue.
 *
 * These are the real definitions, loaded from `data/metrics/definitions/*.yml`
 * through the same registry that validates them for dbt, Cube and the API. Not
 * a fixture: a metrics page showing invented metrics would be the exact thing
 * this product exists to replace.
 *
 * `measure_expression` is deliberately absent from the catalogue. The formula
 * is gated by `metric.view_query_detail`, and a JSON file compiled into a
 * client bundle cannot enforce a capability — it ships to everyone who loads
 * the page. `test_the_catalogue_never_carries_a_formula` fails the build if it
 * ever appears.
 *
 * Certification is computed, never set: it follows from having an owner,
 * executable examples and quality tests, so it cannot be granted by editing a
 * flag.
 */
interface CatalogueEntry {
  key: string;
  name: string;
  description: string;
  owner: string;
  version: number;
  identity: string;
  unit: string;
  grain: string[];
  dimensions: string[];
  sourceModels: string[];
  sensitivity: string;
  qualityTests: string[];
  exampleCount: number;
  isCertified: boolean;
  certificationGaps: string[];
  validFrom: string;
  validTo: string | null;
  isExposureBearing: boolean;
}

const METRICS = catalogue.metrics as CatalogueEntry[];

export default function MetricsPage() {
  const certified = METRICS.filter((metric) => metric.isCertified);
  return (
    <AppShell
      title={`Metrics · ${METRICS.length}`}
      current="/metrics"
      demoNote="These metric definitions are real — loaded from data/metrics/definitions."
      meta={`${certified.length} certified · governed definitions, not fixtures`}
    >
      <div className="route-body">
        {METRICS.map((metric) => (
          <article key={metric.identity} className="metric-card">
            <div className="metric-head">
              <h2>{metric.name}</h2>
              <span className="chip">{metric.identity}</span>
              {metric.isCertified ? (
                <span className="chip chip-low">
                  <span className="chip-glyph" aria-hidden="true">
                    ✓
                  </span>
                  certified
                </span>
              ) : (
                <span className="chip chip-high">
                  <span className="chip-glyph" aria-hidden="true">
                    ◌
                  </span>
                  not certified
                </span>
              )}
              <span className="chip">{metric.sensitivity}</span>
            </div>

            <p className="metric-description">{metric.description}</p>

            <dl className="peek-grid">
              <dt>Owner</dt>
              <dd>{metric.owner}</dd>
              <dt>Unit</dt>
              <dd>{metric.unit}</dd>
              <dt>Grain</dt>
              <dd className="mono">{metric.grain.join(", ")}</dd>
              <dt>Dimensions</dt>
              <dd className="mono">{metric.dimensions.join(", ") || "—"}</dd>
              <dt>Sources</dt>
              <dd className="mono">{metric.sourceModels.join(", ")}</dd>
              <dt>Valid from</dt>
              <dd className="tabular">
                {metric.validFrom}
                {metric.validTo ? ` until ${metric.validTo}` : " · live"}
              </dd>
            </dl>

            <div className="reason-codes" style={{ marginTop: 10 }}>
              {metric.qualityTests.map((test) => (
                <span key={test} className="chip">
                  {humanise(test)}
                </span>
              ))}
              <span className="chip">
                {metric.exampleCount} executable example
                {metric.exampleCount === 1 ? "" : "s"}
              </span>
            </div>

            {metric.certificationGaps.length > 0 ? (
              <p className="action-note" style={{ marginTop: 8 }}>
                Not certified because it is missing: {metric.certificationGaps.join(", ")}.
              </p>
            ) : null}

            <p className="action-note" style={{ marginTop: 8 }}>
              The formula is not shown here. It is gated by{" "}
              <code className="mono">metric.view_query_detail</code>, and a catalogue compiled into
              this page could not enforce that.
            </p>
          </article>
        ))}
      </div>
    </AppShell>
  );
}
