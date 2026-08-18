/**
 * Local ledger state — assignment, transitions and their audit trail.
 *
 * This is the demonstration substitute for the API. It applies the *same*
 * rules, because it asks the same `checkTransition` the server's module
 * generates, and it records the same audit shape. What it does not do is
 * persist: a reload returns to the seeded state, which the banner says.
 *
 * The important property is that the component tree never learns it is talking
 * to a fixture. When the API is hosted, this module becomes a fetch and nothing
 * above it changes — which is only true because the rules were never
 * reimplemented here in the first place.
 */
import { type GapStatus, checkTransition } from "@fitos/contracts/lifecycle";
import type { DemoGap } from "./demo-gaps";

export interface AuditEntry {
  action: string;
  before: string;
  after: string;
  reason: string | null;
  actor: string;
}

export interface LedgerState {
  gaps: DemoGap[];
  audit: Record<string, AuditEntry[]>;
}

export const ACTOR = "DK";

export function assign(state: LedgerState, gapId: string, owner: string | null): LedgerState {
  const gap = state.gaps.find((candidate) => candidate.id === gapId);
  if (!gap || gap.ownerInitials === owner) return state;

  return {
    gaps: state.gaps.map((candidate) =>
      candidate.id === gapId ? { ...candidate, ownerInitials: owner } : candidate,
    ),
    audit: {
      ...state.audit,
      [gapId]: [
        ...(state.audit[gapId] ?? []),
        {
          action: "gap.assigned",
          before: gap.ownerInitials ?? "unassigned",
          after: owner ?? "unassigned",
          reason: null,
          actor: ACTOR,
        },
      ],
    },
  };
}

export function transition(
  state: LedgerState,
  gapId: string,
  request: { to: GapStatus; reasonCode?: string; note?: string },
  capabilities: readonly string[],
): LedgerState {
  const gap = state.gaps.find((candidate) => candidate.id === gapId);
  if (!gap) return state;

  // Checked here as well as in the control that offered it. The UI decides what
  // to *show*; this decides what to *do*, and a state mutation that trusted the
  // button would be one keyboard shortcut away from bypassing the rule.
  const refusal = checkTransition({
    from: gap.status as GapStatus,
    to: request.to,
    capabilities,
    reasonCode: request.reasonCode ?? null,
    note: request.note ?? null,
    outcomeId: request.to === "resolved" ? null : undefined,
    hasOwner: gap.ownerInitials !== null,
  });
  if (refusal) return state;

  return {
    gaps: state.gaps.map((candidate) =>
      candidate.id === gapId ? { ...candidate, status: request.to } : candidate,
    ),
    audit: {
      ...state.audit,
      [gapId]: [
        ...(state.audit[gapId] ?? []),
        {
          action: `gap.${request.to}`,
          before: gap.status,
          after: request.to,
          reason: request.reasonCode ?? null,
          actor: ACTOR,
        },
      ],
    },
  };
}
