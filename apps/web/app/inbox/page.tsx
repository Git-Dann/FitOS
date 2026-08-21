import { Workspace } from "@/components/Workspace";
import { DEMO_GAPS } from "@/lib/demo-gaps";

/**
 * The ledger — Concept A. It moved off `/` when the radar became the home,
 * because the two answer different questions: the radar is "where is it hurting
 * right now", the inbox is "which one do I pick up next". Concept B's own risks
 * say triage does not scale on a grid, so both exist rather than one replacing
 * the other.
 */
export default function Inbox() {
  const open = DEMO_GAPS.filter((gap) => gap.status !== "resolved" && gap.status !== "dismissed");
  return <Workspace gaps={open} />;
}
