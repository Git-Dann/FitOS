import { AppShell } from "@/components/AppShell";
import { GapLedger } from "@/components/GapLedger";
import { DEMO_AS_OF, DEMO_GAPS } from "@/lib/demo-gaps";
import { dateTime } from "@/lib/format";

/**
 * The manager capability set.
 *
 * Hard-coded for the demonstration. In the product this comes from the verified
 * token's membership, resolved per request (ADR 0009) — never from anything the
 * client asserts about itself.
 */
const CAPABILITIES = ["gap.view", "gap.assign", "gap.transition", "gap.dismiss"] as const;

export default function Home() {
  const open = DEMO_GAPS.filter((gap) => gap.status !== "resolved" && gap.status !== "dismissed");
  return (
    <AppShell
      title={`Inbox · ${open.length} open`}
      meta={`as of ${dateTime(DEMO_AS_OF)} · 4 sources · 2 stale`}
    >
      <GapLedger gaps={open} capabilities={CAPABILITIES} />
    </AppShell>
  );
}
