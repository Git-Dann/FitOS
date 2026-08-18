"use client";

import { useState } from "react";
import { SiteShell, Status } from "./FitOSApp";
import { useScenario } from "./scenario-context";
import { useOperations } from "./operations-context";

const queueBars = [35, 54, 42, 68, 88, 79, 57];
const hours = ["10", "11", "12", "13", "14", "15", "16"];

const signals = [
  {
    id: "Chino size 32",
    title: "Restock size 32 / Charcoal",
    detail: "7 requests could not be completed",
    tone: "warn" as const,
    action: "View demand",
  },
  {
    id: "Stock discrepancies",
    title: "Resolve stock accuracy",
    detail: "6 items shown as available were not found",
    tone: "neutral" as const,
    action: "Review list",
  },
  {
    id: "Field Jacket",
    title: "Review Field Jacket / Stone",
    detail: "High try rate, lower keep rate",
    tone: "neutral" as const,
    action: "Inspect item",
  },
];

function ManagerStyles() {
  return (
    <style>{`
    .manager-reframe{max-width:1180px;margin:auto;padding:54px 28px 86px}.manager-topline{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:20px}.manager-topline>span{font-size:11px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:#678278}.manager-reframe h1{font-size:clamp(45px,5.8vw,74px);line-height:.92;letter-spacing:-.08em;margin:0;max-width:690px}.manager-subhead{margin:18px 0 0;max-width:590px;color:#66716e;font-size:16px;line-height:1.5}.manager-controls{display:flex;align-items:center;justify-content:space-between;gap:16px;margin:32px 0 17px}.manager-periods{display:flex;gap:6px}.manager-periods button{border:1px solid #d6ded9;background:#fff;color:#5b6d66;border-radius:999px;padding:8px 13px;font-size:11px;font-weight:700}.manager-periods button.active{background:#294f46;border-color:#294f46;color:#fff}.manager-updated{font-size:11px;color:#71807b}.manager-action{display:grid;grid-template-columns:1.16fr .84fr;gap:28px;align-items:center;background:#254f45;color:#fff;border-radius:16px;padding:29px 31px}.manager-action .eyebrow{color:#b7d9cb;margin:0 0 10px}.manager-action h2{font-size:clamp(29px,3.5vw,43px);line-height:.98;letter-spacing:-.06em;margin:0}.manager-action p:not(.eyebrow){color:#d4e4de;font-size:13px;line-height:1.48;max-width:470px;margin:12px 0 0}.manager-action .button{display:inline-flex;align-items:center;justify-content:center;min-height:40px;padding:0 14px;margin-top:18px;border:1px solid #cfe7dc;border-radius:8px;background:#fff;color:#275747;font-size:12px;font-weight:800}.manager-action-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}.manager-action-stats div{min-height:104px;border:1px solid #ffffff30;border-radius:10px;background:#ffffff10;padding:14px}.manager-action-stats b{display:block;font-size:28px;letter-spacing:-.06em}.manager-action-stats span{display:block;color:#c8ddd5;font-size:10px;line-height:1.35;margin-top:10px}.manager-decision-grid{display:grid;grid-template-columns:1fr 1fr;gap:15px;margin-top:17px}.manager-card{border:1px solid #d9dfdc;border-radius:13px;background:#fff;padding:22px}.manager-card-head{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}.manager-card .eyebrow{margin:0;color:#6f8980}.manager-card h2{font-size:25px;line-height:1;letter-spacing:-.055em;margin:7px 0 0}.manager-card>p{color:#65736e;font-size:12px;line-height:1.45;margin:10px 0 0}.manager-card .status{font-size:10px;white-space:nowrap}.manager-bar-chart{height:136px;display:flex;gap:8px;align-items:end;border-bottom:1px solid #d6dfda;padding:18px 0 18px;margin-top:19px}.manager-bar{display:flex;flex:1;height:100%;align-items:end;position:relative}.manager-bar i{display:block;width:100%;border-radius:4px 4px 0 0;background:#b8d6cb}.manager-bar.peak i{background:#d4a849}.manager-bar span{position:absolute;left:50%;bottom:-18px;transform:translateX(-50%);color:#697973;font-size:9px}.manager-card-foot{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:23px;color:#536a63;font-size:11px}.manager-card-foot b{color:#244f41;font-size:12px}.manager-delivery{display:grid;grid-template-columns:1fr auto;gap:18px;align-items:end;margin-top:30px}.manager-delivery strong{font-size:58px;line-height:.8;letter-spacing:-.09em}.manager-delivery strong span{font-size:22px;letter-spacing:-.05em}.manager-delivery p{font-size:11px;color:#63746e;margin:10px 0 0}.manager-ring{width:96px;height:96px;border-radius:50%;background:conic-gradient(#60927e 0 71%,#e5ece8 71% 100%);display:grid;place-items:center}.manager-ring span{display:grid;place-items:center;width:72px;height:72px;border-radius:50%;background:#fff;color:#315d4f;font-size:12px;font-weight:800}.manager-signal-panel{margin-top:17px;border:1px solid #d9dfdc;border-radius:13px;background:#fff;padding:23px}.manager-signal-heading{display:flex;align-items:end;justify-content:space-between;gap:18px;margin-bottom:6px}.manager-signal-heading h2{font-size:28px;letter-spacing:-.06em;margin:0}.manager-signal-heading p{font-size:11px;color:#687872;margin:0}.manager-signal-list{display:grid}.manager-signal-row{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:14px;border-top:1px solid #dfe5e1;padding:16px 0}.manager-signal-dot{width:9px;height:9px;border-radius:50%;background:#6b9987}.manager-signal-dot.warn{background:#d4a849}.manager-signal-row b{display:block;font-size:13px}.manager-signal-row span{display:block;font-size:11px;color:#6a7973;margin-top:4px}.manager-signal-row button{border:0;background:none;color:#2d6452;font-size:11px;font-weight:800;padding:5px 0}.manager-evidence{display:grid;grid-template-columns:1fr 1fr;gap:15px;margin-top:17px}.manager-evidence article{border-radius:12px;padding:19px;background:#f0f3ef}.manager-evidence .eyebrow{margin:0;color:#6a857b}.manager-evidence b{display:block;font-size:32px;letter-spacing:-.07em;margin:14px 0 6px}.manager-evidence p{font-size:11px;line-height:1.45;color:#64736e;margin:0}.manager-drawer{position:fixed;right:22px;bottom:22px;z-index:30;width:min(370px,calc(100vw - 44px));border:1px solid #d6ded9;border-radius:14px;background:#fff;padding:20px;box-shadow:0 20px 50px #19372c2b}.manager-drawer h3{font-size:23px;letter-spacing:-.055em;margin:7px 0}.manager-drawer p:not(.eyebrow){color:#66716e;font-size:12px;line-height:1.5}.manager-drawer button{border:0;background:none;color:#285e4e;font-size:11px;font-weight:800;padding:0}@media(max-width:760px){.manager-reframe{padding:38px 18px 64px}.manager-action,.manager-decision-grid,.manager-evidence{grid-template-columns:1fr}.manager-action-stats{grid-template-columns:repeat(3,1fr)}.manager-signal-heading{align-items:flex-start;flex-direction:column}.manager-controls{align-items:flex-start;flex-direction:column;margin-top:24px}.manager-signal-row{grid-template-columns:auto 1fr}.manager-signal-row button{grid-column:2;justify-self:start}.manager-subhead{font-size:14px}.manager-action{padding:24px}.manager-card{padding:18px}}@media(max-width:420px){.manager-reframe h1{font-size:46px}.manager-action-stats{gap:6px}.manager-action-stats div{padding:10px;min-height:90px}.manager-action-stats b{font-size:23px}.manager-action-stats span{font-size:9px}.manager-periods button{padding-inline:10px}.manager-topline{align-items:flex-start;flex-direction:column}.manager-delivery strong{font-size:52px}}
  `}</style>
  );
}

export function ManagerAnalytics() {
  const { scenario } = useScenario();
  const { lastUpdate } = useOperations();
  const [period, setPeriod] = useState("Today");
  const [drawer, setDrawer] = useState<string | null>(null);

  return (
    <SiteShell>
      <ManagerStyles />
      <main className="manager-reframe">
        <div className="manager-topline">
          <span>Manager view · Floor 1</span>
          <Status tone={scenario === "Stock Discrepancy" ? "warn" : "good"}>
            {scenario}
          </Status>
        </div>
        <h1>Catch the next missed sale.</h1>
        <p className="manager-subhead">
          A decision view for service pressure, unavailable demand and the next
          practical action.
        </p>
        <div className="manager-controls">
          <div className="manager-periods">
            {["Today", "Last 7 days"].map((item) => (
              <button
                className={period === item ? "active" : ""}
                key={item}
                onClick={() => setPeriod(item)}
              >
                {item}
              </button>
            ))}
          </div>
          <span className="manager-updated">Latest update · {lastUpdate}</span>
        </div>

        <section
          className="manager-action"
          aria-labelledby="manager-action-title"
        >
          <div>
            <p className="eyebrow">Priority action</p>
            <h2 id="manager-action-title">
              Check size 32 / Charcoal before the next peak.
            </h2>
            <p>
              Seven requests could not be completed. This is the clearest place
              to protect demand today.
            </p>
            <button
              className="button"
              onClick={() => setDrawer("Size 32 / Charcoal demand")}
            >
              View the evidence
            </button>
          </div>
          <div className="manager-action-stats">
            <div>
              <b>7</b>
              <span>unmet requests</span>
            </div>
            <div>
              <b>14–15</b>
              <span>peak hours</span>
            </div>
            <div>
              <b>£1.1k</b>
              <span>indicative demand</span>
            </div>
          </div>
        </section>

        <section
          className="manager-decision-grid"
          aria-label="Live operating picture"
        >
          <article className="manager-card">
            <div className="manager-card-head">
              <div>
                <p className="eyebrow">Queue pressure</p>
                <h2>Busy window ahead</h2>
              </div>
              <Status tone="warn">14:00–15:00</Status>
            </div>
            <p>
              Requests rise fastest in the afternoon. Put a colleague close to
              fitting rooms before the peak.
            </p>
            <div
              className="manager-bar-chart"
              role="img"
              aria-label="Requests increase most at 14:00 and 15:00"
            >
              {queueBars.map((height, index) => (
                <div
                  className={
                    index === 4 || index === 5
                      ? "manager-bar peak"
                      : "manager-bar"
                  }
                  key={hours[index]}
                >
                  <i style={{ height: `${height}%` }} />
                  <span>{hours[index]}</span>
                </div>
              ))}
            </div>
            <div className="manager-card-foot">
              <span>84 requests today</span>
              <b>Plan one extra hand-off</b>
            </div>
          </article>
          <article className="manager-card">
            <div className="manager-card-head">
              <div>
                <p className="eyebrow">Delivery health</p>
                <h2>Service is holding</h2>
              </div>
              <Status tone="good">Observed</Status>
            </div>
            <p>
              Most fitting-room requests are reaching the customer within the
              promise.
            </p>
            <div className="manager-delivery">
              <div>
                <strong>
                  71<span>%</span>
                </strong>
                <p>
                  within the promised window
                  <br />
                  Median wait: 4m 12s
                </p>
              </div>
              <div
                className="manager-ring"
                aria-label="71 percent within promise"
              >
                <span>71%</span>
              </div>
            </div>
            <div className="manager-card-foot">
              <span>31 pick trips</span>
              <b>8 batched routes</b>
            </div>
          </article>
        </section>

        <section
          className="manager-signal-panel"
          aria-labelledby="manager-signals-title"
        >
          <div className="manager-signal-heading">
            <div>
              <p className="eyebrow">Review next</p>
              <h2 id="manager-signals-title">Three signals worth acting on.</h2>
            </div>
            <p>Observed data, not a performance claim.</p>
          </div>
          <div className="manager-signal-list">
            {signals.map((signal) => (
              <article className="manager-signal-row" key={signal.id}>
                <i
                  className={`manager-signal-dot ${signal.tone === "warn" ? "warn" : ""}`}
                />
                <div>
                  <b>{signal.title}</b>
                  <span>{signal.detail}</span>
                </div>
                <button onClick={() => setDrawer(signal.id)}>
                  {signal.action} →
                </button>
              </article>
            ))}
          </div>
        </section>

        <section className="manager-evidence" aria-label="Supporting evidence">
          <article>
            <p className="eyebrow">Customer response</p>
            <b>41%</b>
            <p>
              of relevant alternatives were accepted, suggesting recommendations
              can recover part of an unavailable request.
            </p>
          </article>
          <article>
            <p className="eyebrow">Planning signal</p>
            <b>16</b>
            <p>
              recorded unavailable requests contribute to an indicative £1.1k
              demand view. Validate with retailer data before actioning spend.
            </p>
          </article>
        </section>

        {drawer && (
          <aside className="manager-drawer">
            <p className="eyebrow">Evidence</p>
            <h3>{drawer}</h3>
            <p>
              Review request history, stock confidence and fulfilment outcomes
              before changing stock, placement or staffing. This demonstration
              uses deterministic local data.
            </p>
            <button onClick={() => setDrawer(null)}>Close</button>
          </aside>
        )}
      </main>
    </SiteShell>
  );
}
