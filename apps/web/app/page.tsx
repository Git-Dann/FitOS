import { AppShell } from "@/components/AppShell";
import { Workspace } from "@/components/Workspace";
import { DEMO_AS_OF, DEMO_GAPS } from "@/lib/demo-gaps";
import { dateTime } from "@/lib/format";

export default function Home() {
  const open = DEMO_GAPS.filter((gap) => gap.status !== "resolved" && gap.status !== "dismissed");
  return (
    <AppShell
      title={`Inbox · ${open.length} open`}
      meta={`as of ${dateTime(DEMO_AS_OF)} · 4 sources · 2 stale`}
    >
      <Workspace gaps={open} />
    </AppShell>
  );
}
