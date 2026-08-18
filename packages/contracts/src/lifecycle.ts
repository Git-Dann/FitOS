/**
 * The gap lifecycle, read from the generated contract.
 *
 * The transition table is *not* written here. It is generated from
 * `services/api/src/fitos_api/gaps/lifecycle.py`, which is where it is
 * enforced, and `test_lifecycle_contract_matches_the_module` fails if the
 * committed JSON drifts. Retyping the edges in TypeScript would produce two
 * tables that agree until somebody edits one — and the failure mode is the
 * worst kind: the UI offers a transition the API refuses, or hides one it
 * allows, and neither is visible in a test that only exercises one side.
 */
import contract from "./gap-lifecycle.json" with { type: "json" };

export type GapStatus =
  | "detected"
  | "triaged"
  | "investigating"
  | "actioned"
  | "validating"
  | "resolved"
  | "dismissed";

export type Capability = "gap.transition" | "gap.dismiss";

const TRANSITIONS = contract.transitions as Record<string, string[]>;
const TRANSITION_CAPABILITY = contract.transitionCapability as Record<string, string>;

export const GAP_STATUSES = contract.statuses as GapStatus[];
export const TERMINAL_STATUSES = contract.terminal as GapStatus[];
export const DISMISSAL_REASONS = contract.dismissalReasons as string[];

export function isTerminal(status: GapStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}

/** Every status reachable from this one. Empty for a terminal status. */
export function legalTransitions(status: GapStatus): GapStatus[] {
  return (TRANSITIONS[status] ?? []) as GapStatus[];
}

/**
 * The capability a transition needs.
 *
 * Dismissal is separate from the rest on purpose: emptying a ledger is a
 * different act from advancing work through it, and a caller who may advance a
 * gap must not thereby be able to make it disappear.
 */
export function capabilityFor(target: GapStatus): Capability {
  return (TRANSITION_CAPABILITY[target] ?? "gap.transition") as Capability;
}

export interface TransitionRefusal {
  reason: "illegal" | "terminal" | "not_permitted" | "missing_requirement";
  message: string;
}

/**
 * Whether a transition may be offered, and why not when it may not.
 *
 * This mirrors the order the API checks in — permission, then legality, then
 * requirements — so a refusal shown in the UI reads the same as the one the API
 * would return. A client that guessed a different order would explain the wrong
 * thing to the user.
 */
export function checkTransition(args: {
  from: GapStatus;
  to: GapStatus;
  capabilities: readonly string[];
  // `| undefined` is required under exactOptionalPropertyTypes: an optional
  // property that cannot hold undefined cannot be passed one explicitly, which
  // every caller doing `reasonCode: maybe` would then fail on.
  reasonCode?: string | null | undefined;
  note?: string | null | undefined;
  outcomeId?: string | null | undefined;
  hasOwner: boolean;
}): TransitionRefusal | null {
  const needed = capabilityFor(args.to);
  if (!args.capabilities.includes(needed)) {
    return { reason: "not_permitted", message: `Requires ${needed}` };
  }

  if (!legalTransitions(args.from).includes(args.to)) {
    if (isTerminal(args.from)) {
      return {
        reason: "terminal",
        message: `${args.from} is terminal; reopening is a new gap, not a transition`,
      };
    }
    return {
      reason: "illegal",
      message: `${args.from} → ${args.to} is not a legal transition`,
    };
  }

  if (args.to === "dismissed") {
    if (!args.reasonCode || !DISMISSAL_REASONS.includes(args.reasonCode)) {
      return { reason: "missing_requirement", message: "Dismissal needs a reason code" };
    }
    if (!args.note || args.note.trim().length === 0) {
      return {
        reason: "missing_requirement",
        message:
          "Dismissal needs a note; a reason code alone does not tell the next person why this gap was not worth acting on",
      };
    }
  }

  if (args.to === "resolved" && !args.outcomeId) {
    return {
      reason: "missing_requirement",
      message:
        "Resolution needs an outcome; recording no measurable change is an outcome, recording nothing is not",
    };
  }

  if (args.to === "triaged" && !args.hasOwner) {
    return {
      reason: "missing_requirement",
      message: "Triage sets an owner; a triaged gap nobody owns is an unread gap with a label",
    };
  }

  return null;
}
