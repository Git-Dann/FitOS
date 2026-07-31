"use client";

import { useState } from "react";
import Link from "next/link";
import { SiteShell, Status } from "./FitOSApp";

const outcomes = [
  [
    "Service",
    "Keep requests within a clear promise",
    "Wait time · within-promise rate",
  ],
  [
    "Demand",
    "See which requests could not be fulfilled",
    "Unavailable variants · alternatives accepted",
  ],
  [
    "Team",
    "Test a workable hand-off on the floor",
    "Requests per hour · route efficiency",
  ],
];

const phases = [
  ["01", "Align", "Choose the floor and question."],
  ["02", "Baseline", "Understand the current rhythm."],
  ["03", "Run", "Operate alongside the store."],
  ["04", "Decide", "Stop, extend or plan rollout."],
];

function PilotStyles() {
  return (
    <style>{`
    .pilot-reframed{max-width:1180px;margin:auto;padding:56px 28px 84px}.pilot-kicker{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:26px}.pilot-kicker>span{font-size:11px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:#668177}.pilot-reframed h1{max-width:760px;font-size:clamp(49px,6.2vw,82px);line-height:.9;letter-spacing:-.085em;margin:0}.pilot-lede-reframed{max-width:630px;margin:20px 0 27px;color:#66716e;font-size:17px;line-height:1.55}.pilot-hero-actions{display:flex;align-items:center;gap:18px;flex-wrap:wrap}.pilot-hero-actions .text-link{color:#2e6552;font-size:12px;font-weight:800}.pilot-fact-row{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin-top:48px}.pilot-fact-row article{border-top:2px solid #78a18e;padding:13px 3px 0}.pilot-fact-row span{display:block;color:#688177;font-size:10px;font-weight:800;letter-spacing:.1em}.pilot-fact-row b{display:block;margin:15px 0 5px;font-size:22px;letter-spacing:-.05em}.pilot-fact-row small{color:#697873;font-size:11px;line-height:1.35}.pilot-brief{display:grid;grid-template-columns:.85fr 1.15fr;gap:44px;margin-top:70px;padding:31px;background:#eef3ef;border-radius:16px}.pilot-brief .eyebrow{margin:0 0 10px}.pilot-brief h2,.pilot-section h2{font-size:clamp(30px,3.6vw,47px);line-height:1;letter-spacing:-.065em;margin:0}.pilot-brief p:not(.eyebrow){font-size:13px;line-height:1.5;color:#5d6e67;margin:13px 0 0}.pilot-config{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;align-content:start}.pilot-config button{min-height:108px;border:1px solid #d1ddd6;border-radius:10px;background:#fff;padding:13px;text-align:left;color:#586a63}.pilot-config button.active{border-color:#5f927d;background:#dfeee4;color:#274f42;box-shadow:inset 0 0 0 1px #5f927d}.pilot-config span{display:block;font-size:10px;text-transform:uppercase;letter-spacing:.08em}.pilot-config b{display:block;margin-top:17px;font-size:18px;letter-spacing:-.04em}.pilot-section{padding:72px 0;border-bottom:1px solid #d9dfdc}.pilot-section-head{display:flex;align-items:end;justify-content:space-between;gap:25px}.pilot-section-head>p{max-width:390px;margin:0;color:#687772;font-size:13px;line-height:1.45}.pilot-outcomes{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:29px}.pilot-outcomes article{border:1px solid #d9dfdc;border-radius:12px;background:#fff;padding:19px;min-height:185px}.pilot-outcomes span{font-size:10px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:#638478}.pilot-outcomes b{display:block;font-size:20px;line-height:1.08;letter-spacing:-.045em;margin:34px 0 12px}.pilot-outcomes small{display:block;color:#687773;font-size:11px;line-height:1.4}.pilot-rhythm{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:29px}.pilot-rhythm article{border-top:2px solid #6d9886;padding:14px 2px 0}.pilot-rhythm span{font-size:10px;color:#6b897e;letter-spacing:.1em}.pilot-rhythm b{display:block;font-size:20px;letter-spacing:-.04em;margin:20px 0 7px}.pilot-rhythm small{font-size:11px;color:#687772;line-height:1.35}.pilot-measure{display:grid;grid-template-columns:1.05fr .95fr;gap:45px;align-items:center;margin-top:29px;padding:29px 31px;border-radius:14px;background:#274f45;color:#fff}.pilot-measure .eyebrow{color:#b8d9cb;margin:0 0 8px}.pilot-measure h3{font-size:30px;line-height:1.02;letter-spacing:-.055em;margin:0}.pilot-measure p:not(.eyebrow){font-size:12px;line-height:1.48;color:#cde0d9;margin:13px 0 0}.pilot-measure-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}.pilot-measure-grid div{border:1px solid #ffffff2e;border-radius:8px;background:#ffffff10;padding:13px}.pilot-measure-grid span{display:block;color:#bdd8ce;font-size:9px;letter-spacing:.08em;text-transform:uppercase}.pilot-measure-grid b{display:block;font-size:14px;line-height:1.18;margin-top:9px}.pilot-boundaries{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:29px}.pilot-boundaries article{border:1px solid #d9dfdc;border-radius:11px;background:#fff;padding:18px}.pilot-boundaries h3{font-size:18px;letter-spacing:-.04em;margin:18px 0 7px}.pilot-boundaries p{font-size:11px;line-height:1.45;color:#677771;margin:0}.pilot-details{margin-top:12px;border-top:1px solid #d9dfdc}.pilot-details details{border-bottom:1px solid #d9dfdc;padding:14px 0}.pilot-details summary{cursor:pointer;font-size:13px;font-weight:800;color:#294f43}.pilot-details p{max-width:690px;color:#64736e;font-size:12px;line-height:1.5;margin:9px 0 0}.pilot-contact{display:grid;grid-template-columns:.88fr 1.12fr;gap:54px;margin-top:72px;border-radius:15px;background:#f4ead1;padding:37px}.pilot-contact .eyebrow{margin:0 0 9px;color:#746343}.pilot-contact h2{font-size:clamp(31px,3.8vw,49px);line-height:1;letter-spacing:-.065em;margin:0}.pilot-contact p:not(.eyebrow){font-size:13px;line-height:1.48;color:#685f4d;margin:15px 0 0}.pilot-form{display:grid;grid-template-columns:1fr 1fr;gap:8px;align-content:start}.pilot-form input,.pilot-form select{min-height:43px;border:1px solid #d6c89f;border-radius:7px;background:#fffdf7;color:#26322f;padding:0 11px;font-size:12px}.pilot-form select{grid-column:span 2}.pilot-form button{grid-column:span 2;min-height:44px;border:1px solid #305b4d;border-radius:7px;background:#305b4d;color:#fff;font-size:12px;font-weight:800}.pilot-confirm{grid-column:span 2;margin:4px 0 0;color:#4e6b5d;font-size:12px;font-weight:700}@media(max-width:780px){.pilot-reframed{padding:40px 20px 64px}.pilot-fact-row,.pilot-outcomes{grid-template-columns:repeat(2,1fr)}.pilot-brief,.pilot-measure,.pilot-contact{grid-template-columns:1fr;gap:28px}.pilot-section-head{align-items:flex-start;flex-direction:column}.pilot-rhythm{grid-template-columns:repeat(2,1fr)}.pilot-contact{padding:27px}.pilot-kicker{margin-bottom:22px}}@media(max-width:440px){.pilot-reframed{padding-inline:16px}.pilot-reframed h1{font-size:49px}.pilot-fact-row,.pilot-outcomes,.pilot-rhythm,.pilot-boundaries,.pilot-config,.pilot-measure-grid{grid-template-columns:1fr}.pilot-fact-row{gap:18px}.pilot-config button{min-height:78px}.pilot-config b{margin-top:8px}.pilot-form{grid-template-columns:1fr}.pilot-form input,.pilot-form select,.pilot-form button,.pilot-confirm{grid-column:span 1}.pilot-contact{padding:23px}.pilot-kicker{align-items:flex-start;flex-direction:column}}
  `}</style>
  );
}

export function PilotStory() {
  const [scope, setScope] = useState("6–14 rooms");
  const [sent, setSent] = useState(false);

  return (
    <SiteShell>
      <PilotStyles />
    <section className="pilot-reframed">
        <div className="pilot-kicker">
          <span>FitOS pilot</span>
          <Status tone="good">Evidence-led, not promise-led</Status>
        </div>
        <h1>Prove the next fitting-room operating model.</h1>
        <p className="pilot-lede-reframed">
          A focused trial shows where demand appears, whether the team can
          fulfil it, and what to change before a wider rollout.
        </p>
        <div className="pilot-hero-actions">
          <Link className="button" href="/demo/manager">
            See the decision view <span>→</span>
          </Link>
          <Link className="text-link" href="/demo">
            Return to guided demo →
          </Link>
        </div>
        <div className="pilot-fact-row">
          <article>
            <span>01</span>
            <b>One store</b>
            <small>One practical learning environment.</small>
          </article>
          <article>
            <span>02</span>
            <b>6–14 rooms</b>
            <small>Enough volume to observe patterns.</small>
          </article>
          <article>
            <span>03</span>
            <b>One category</b>
            <small>Start where requests are frequent.</small>
          </article>
          <article>
            <span>04</span>
            <b>4–8 weeks</b>
            <small>Baseline, live learning, decision.</small>
          </article>
        </div>

        <section className="pilot-brief">
          <div>
            <p className="eyebrow">Choose a focused scope</p>
            <h2>Small enough to run. Meaningful enough to learn.</h2>
            <p>
              Start with the rooms where the team can act on the evidence within
              the same shift.
            </p>
          </div>
          <div className="pilot-config" aria-label="Pilot room scope">
            {["6–8 rooms", "9–14 rooms", "14+ rooms"].map((item) => (
              <button
                className={
                  scope === item ||
                  (scope === "6–14 rooms" && item === "9–14 rooms")
                    ? "active"
                    : ""
                }
                onClick={() => setScope(item)}
                key={item}
              >
                <span>Scope</span>
                <b>{item}</b>
              </button>
            ))}
          </div>
        </section>

        <section className="pilot-section">
          <div className="pilot-section-head">
            <div>
              <p className="eyebrow">What the pilot validates</p>
              <h2>Three useful answers, not a dashboard.</h2>
            </div>
            <p>
              Each measure links a customer moment to an operational decision
              the store can validate locally.
            </p>
          </div>
          <div className="pilot-outcomes">
            {outcomes.map(([label, title, measure]) => (
              <article key={label}>
                <span>{label}</span>
                <b>{title}</b>
                <small>{measure}</small>
              </article>
            ))}
          </div>
        </section>

        <section className="pilot-section">
          <div className="pilot-section-head">
            <div>
              <p className="eyebrow">Pilot rhythm</p>
              <h2>Four moves to an evidence-led decision.</h2>
            </div>
            <p>
              No big-bang integration. The work builds from the store you
              already operate.
            </p>
          </div>
          <div className="pilot-rhythm">
            {phases.map(([number, title, detail]) => (
              <article key={number}>
                <span>{number}</span>
                <b>{title}</b>
                <small>{detail}</small>
              </article>
            ))}
          </div>
          <div className="pilot-measure">
            <div>
              <p className="eyebrow">Primary measure</p>
              <h3>Can requests be fulfilled within the promised time?</h3>
              <p>
                Read this alongside room pressure, stock confidence and
                colleague feedback. It is an observed service measure, not a
                commercial guarantee.
              </p>
            </div>
            <div className="pilot-measure-grid">
              <div>
                <span>Service</span>
                <b>Within-promise rate</b>
              </div>
              <div>
                <span>Demand</span>
                <b>Unmet product requests</b>
              </div>
              <div>
                <span>Team</span>
                <b>Requests per staff hour</b>
              </div>
              <div>
                <span>Decision</span>
                <b>Stop, extend or rollout</b>
              </div>
            </div>
          </div>
        </section>

        <section className="pilot-section">
          <div className="pilot-section-head">
            <div>
              <p className="eyebrow">Clear boundary</p>
              <h2>Designed around the store you already run.</h2>
            </div>
            <p>
              FitOS coordinates intent and fulfilment; it does not replace
              retailer systems.
            </p>
          </div>
          <div className="pilot-boundaries">
            <article>
              <Status tone="good">In scope</Status>
              <h3>Existing labels and devices</h3>
              <p>
                Garment barcodes and existing customer phones or tablets are
                enough to begin. RFID remains optional.
              </p>
            </article>
            <article>
              <Status>Not a production integration</Status>
              <h3>Test before you scale</h3>
              <p>
                No live payments, authentication or retailer-system connection
                is implied by this prototype.
              </p>
            </article>
          </div>
          <div className="pilot-details">
            <details>
              <summary>What data is useful?</summary>
              <p>
                A usable product catalogue, a stock or availability input, and
                agreement on the rooms and service promise to test.
              </p>
            </details>
            <details>
              <summary>What happens after the pilot?</summary>
              <p>
                Use observed demand, service outcomes and team feedback to stop,
                extend the learning period or prepare a rollout plan.
              </p>
            </details>
          </div>
        </section>

        <section className="pilot-contact">
          <div>
            <p className="eyebrow">Plan a pilot</p>
            <h2>Start with the store question worth answering.</h2>
            <p>
              This is a local demonstration form. It records interest in this
              session only and does not submit information anywhere.
            </p>
          </div>
          <form
            className="pilot-form"
            onSubmit={(event) => {
              event.preventDefault();
              setSent(true);
            }}
          >
            <input
              aria-label="Work email"
              placeholder="Work email"
              type="email"
              required
            />
            <input
              aria-label="Retailer or brand"
              placeholder="Retailer or brand"
              required
            />
            <select aria-label="Rooms in scope" defaultValue="">
              <option value="" disabled>
                Rooms in scope
              </option>
              <option>6–8 rooms</option>
              <option>9–14 rooms</option>
              <option>More than 14 rooms</option>
            </select>
            <button type="submit">Request a pilot discussion</button>
            {sent && (
              <p className="pilot-confirm">
                Interest saved for this local session.
              </p>
            )}
          </form>
        </section>
    </section>
    </SiteShell>
  );
}
