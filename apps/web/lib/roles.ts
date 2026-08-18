/**
 * Roles, capabilities, and the exposure filter.
 *
 * The capability map mirrors `fitos_api.capabilities`. It is duplicated here
 * rather than generated, and that is a deliberate, bounded exception: this file
 * decides what the *demonstration* shows, not what any real caller may do. In
 * the product the capability set arrives resolved from the caller's membership
 * (ADR 0009) and the client is never asked what it is allowed to do.
 *
 * The important part is `withheldForCapabilities`. The API removes exposure
 * fields from the payload before it is sent — absent, not null and not masked —
 * and this reproduces that at the data boundary rather than hiding fields in a
 * component. The distinction is the whole control: a UI that receives a number
 * and declines to draw it has still received the number, and anybody who opens
 * the network tab has it.
 */
import type { DemoGap } from "./demo-gaps";

export type Role = "frontline" | "manager" | "analyst" | "admin";

const FRONTLINE = ["gap.view", "gap.comment"] as const;

const MANAGER = [
  ...FRONTLINE,
  "gap.assign",
  "gap.transition",
  "gap.dismiss",
  "gap.view_exposure",
  "metric.view",
  "metric.query",
  "source.view",
] as const;

const ANALYST = [...MANAGER, "metric.view_query_detail"] as const;

const ADMIN = [
  ...ANALYST,
  "source.manage",
  "mapping.manage",
  "member.manage",
  "audit.view",
] as const;

export const ROLE_CAPABILITIES: Record<Role, readonly string[]> = {
  frontline: FRONTLINE,
  manager: MANAGER,
  analyst: ANALYST,
  admin: ADMIN,
};

export const ROLES: Role[] = ["frontline", "manager", "analyst", "admin"];

/** The fields the API strips when the caller lacks `gap.view_exposure`. */
export const EXPOSURE_FIELDS = [
  "exposureLow",
  "exposureBase",
  "exposureHigh",
  "currency",
  "assumptions",
] as const;

/**
 * Reason codes that describe the withheld figure rather than the finding.
 *
 * Leaving `modelled_exposure` on a stripped payload tells the reader an
 * exposure exists and is being kept from them — which is the disclosure the
 * removal was for. The codes about *why the gap fired* stay, because those are
 * the finding and everyone may see it.
 */
const EXPOSURE_REASON_CODES = ["modelled_exposure", "wide_exposure_interval"];

/**
 * Strip exposure from gaps a caller may not see it on.
 *
 * Applied where the payload is built, not where it is rendered — this stands in
 * for the API's `serialise()`. The fields are *removed*: a null on a ledger
 * where most gaps carry a figure still says "there is a number here you may not
 * see", which is itself a disclosure.
 */
export function withheldForCapabilities(
  gaps: DemoGap[],
  capabilities: readonly string[],
): DemoGap[] {
  if (capabilities.includes("gap.view_exposure")) return gaps;
  return gaps.map((gap) => {
    const stripped = { ...gap };
    for (const field of EXPOSURE_FIELDS) {
      delete (stripped as Record<string, unknown>)[field];
    }
    // `isModelled`, the formula and the exposure reason codes would each leak
    // the shape of what was withheld.
    stripped.isModelled = false;
    stripped.formulaLabel = null;
    stripped.assumptions = [];
    stripped.reasonCodes = gap.reasonCodes.filter((code) => !EXPOSURE_REASON_CODES.includes(code));
    return stripped;
  });
}
