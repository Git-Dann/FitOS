import { AppShell } from "@/components/AppShell";
import { DEMO_SOURCES, SOURCE_STATE_GLYPH } from "@/lib/demo-sources";
import { age, count, dateTime } from "@/lib/format";

/**
 * Sources — connector state, honestly.
 *
 * The rule this route exists to honour is CLAUDE.md's *no fake status*: a
 * connector card shows its real state and `fixture` is never dressed as
 * `healthy`. Two of the six here have never connected to anything, and they say
 * so rather than borrowing a green badge to make the page look finished. A demo
 * where everything is green teaches the reader that green means nothing.
 *
 * Accepted and rejected counts are both shown, always. A source that is
 * arriving on time while rejecting 59% of what it sends is not healthy, and a
 * card showing only the accepted count would call it healthy.
 */
export default function SourcesPage() {
  const live = DEMO_SOURCES.filter((source) => source.state !== "fixture");
  return (
    <AppShell
      title={`Sources · ${DEMO_SOURCES.length}`}
      current="/sources"
      demoNote="Four of these connectors are seeded state and two have never run."
      meta={`${live.length} configured · ${DEMO_SOURCES.length - live.length} fixtures`}
    >
      <div className="route-body">
        <div className="table-scroll">
          <table className="table">
            <caption className="visually-hidden">
              Connector sources with their state, freshness and record counts
            </caption>
            <thead>
              <tr>
                <th scope="col">Source</th>
                <th scope="col">State</th>
                <th scope="col">Age</th>
                <th scope="col">Cadence</th>
                <th scope="col">Accepted</th>
                <th scope="col">Rejected</th>
                <th scope="col">Last run</th>
              </tr>
            </thead>
            <tbody>
              {DEMO_SOURCES.map((source) => (
                <tr key={source.key}>
                  <th scope="row">
                    {source.label}
                    <div className="mono">{source.connector}</div>
                  </th>
                  <td>
                    <span className={`chip chip-severity chip-source-${source.state}`}>
                      <span className="chip-dot" aria-hidden="true" />
                      <span className="chip-glyph" aria-hidden="true">
                        {SOURCE_STATE_GLYPH[source.state]}
                      </span>
                      {source.state.replace("_", " ")}
                    </span>
                  </td>
                  <td className="tabular">
                    {source.ageSeconds === null ? (
                      <span className="exposure-none">never reported</span>
                    ) : (
                      age(source.ageSeconds)
                    )}
                  </td>
                  <td className="tabular">{age(source.expectedLatencySeconds)}</td>
                  <td className="tabular">{count(source.recordsAccepted)}</td>
                  <td className="tabular">
                    {source.recordsRejected > 0 ? (
                      <strong>{count(source.recordsRejected)}</strong>
                    ) : (
                      count(source.recordsRejected)
                    )}
                  </td>
                  <td className="tabular">{source.lastRunAt ? dateTime(source.lastRunAt) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="route-notes">
          {DEMO_SOURCES.map((source) => (
            <p key={source.key}>
              <strong>{source.label}</strong> · {source.note}
            </p>
          ))}
        </div>
      </div>
    </AppShell>
  );
}
