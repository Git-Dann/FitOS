"use client";

/**
 * Assign, advance and dismiss — the actions on a gap.
 *
 * Every rule here comes from `@fitos/contracts/lifecycle`, which is generated
 * from the API's own module. Nothing about the workflow is decided in this
 * file: it asks `checkTransition` and renders the answer. That is deliberate,
 * because a UI that decides for itself which transitions are legal is a UI that
 * eventually disagrees with the server, and the disagreement shows up as a
 * button that produces a 422.
 *
 * Illegal transitions are *not offered*. Refused-but-visible controls teach
 * people to click and see, which is the opposite of a ledger you can work
 * quickly. Where a transition is legal but incomplete — a dismissal with no
 * note — the control is offered and the refusal is explained inline, because
 * there the user can actually do something about it.
 */
import { useState } from "react";
import {
  DISMISSAL_REASONS,
  type GapStatus,
  checkTransition,
  isTerminal,
  legalTransitions,
} from "@fitos/contracts/lifecycle";
import type { DemoGap } from "@/lib/demo-gaps";
import { humanise } from "@/lib/format";

export interface TransitionRequest {
  to: GapStatus;
  reasonCode?: string;
  note?: string;
}

const OWNERS = ["RS", "AM", "LK", "DK"];

export function TransitionControls({
  gap,
  capabilities,
  onAssign,
  onTransition,
}: {
  gap: DemoGap;
  capabilities: readonly string[];
  onAssign: (owner: string | null) => void;
  onTransition: (request: TransitionRequest) => void;
}) {
  const [dismissing, setDismissing] = useState(false);
  const [reasonCode, setReasonCode] = useState<string>(DISMISSAL_REASONS[0] ?? "duplicate");
  const [note, setNote] = useState("");

  const status = gap.status as GapStatus;

  if (isTerminal(status)) {
    return (
      <section className="peek-section">
        <p className="peek-label">Actions</p>
        <p className="action-note">
          This gap is {status}. Terminal states accept no transitions — the same condition recurring
          is new work, not a reopening, and the detector will raise it again.
        </p>
      </section>
    );
  }

  const targets = legalTransitions(status).filter((target) => target !== "dismissed");

  const dismissRefusal = checkTransition({
    from: status,
    to: "dismissed",
    capabilities,
    reasonCode,
    note,
    hasOwner: gap.ownerInitials !== null,
  });

  return (
    <section className="peek-section">
      <p className="peek-label">Actions</p>

      <div className="action-row">
        <label className="action-label" htmlFor="owner">
          Owner
        </label>
        <select
          id="owner"
          className="control"
          value={gap.ownerInitials ?? ""}
          onChange={(event) => onAssign(event.target.value || null)}
        >
          <option value="">unassigned</option>
          {OWNERS.map((owner) => (
            <option key={owner} value={owner}>
              {owner}
            </option>
          ))}
        </select>
      </div>

      <div className="action-row">
        {targets.map((target) => {
          const refusal = checkTransition({
            from: status,
            to: target,
            capabilities,
            hasOwner: gap.ownerInitials !== null,
            // A resolution needs an outcome, which is recorded on the detail
            // route. Passing a placeholder here would let the UI claim a
            // resolution the API would refuse.
            outcomeId: target === "resolved" ? null : undefined,
          });
          return (
            <button
              key={target}
              type="button"
              className={
                target === targets[0]
                  ? "control control-action control-primary"
                  : "control control-action"
              }
              disabled={refusal !== null}
              title={refusal?.message}
              onClick={() => onTransition({ to: target })}
            >
              {humanise(target)}
            </button>
          );
        })}

        <button
          type="button"
          className="control"
          onClick={() => setDismissing((open) => !open)}
          aria-expanded={dismissing}
        >
          Dismiss…
        </button>
      </div>

      {/* The requirements are shown, not hidden behind a failed submit.
          Dismissal is how a ledger gets quietly emptied, so the cost of doing
          it is visible before the click rather than after. */}
      {dismissing ? (
        <div className="dismiss-form">
          <label className="action-label" htmlFor="reason">
            Reason
          </label>
          <select
            id="reason"
            className="control"
            value={reasonCode}
            onChange={(event) => setReasonCode(event.target.value)}
          >
            {DISMISSAL_REASONS.map((reason) => (
              <option key={reason} value={reason}>
                {humanise(reason)}
              </option>
            ))}
          </select>

          <label className="action-label" htmlFor="note">
            Note
          </label>
          <textarea
            id="note"
            className="control"
            rows={2}
            value={note}
            placeholder="Why is this particular gap not worth acting on?"
            aria-invalid={dismissRefusal !== null}
            aria-describedby={dismissRefusal ? "dismiss-refusal" : undefined}
            onChange={(event) => setNote(event.target.value)}
          />

          {/* A refusal has to look like one. This rendered in --fg-muted with
              no glyph and no border change, which put it 25 luminance units
              from a field label — the copy was right and the treatment threw it
              away. The live region is what makes it reach a screen reader when
              it appears after the control was already focused. */}
          {dismissRefusal ? (
            <p className="action-refusal" id="dismiss-refusal" role="status">
              <span aria-hidden="true">⚠</span> {dismissRefusal.message}
            </p>
          ) : null}

          <button
            type="button"
            className="control control-action"
            disabled={dismissRefusal !== null}
            onClick={() => {
              onTransition({ to: "dismissed", reasonCode, note });
              setDismissing(false);
              setNote("");
            }}
          >
            Dismiss gap
          </button>
        </div>
      ) : null}
    </section>
  );
}
