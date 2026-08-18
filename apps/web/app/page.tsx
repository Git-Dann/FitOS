import { Workspace } from "@/components/Workspace";
import { DEMO_GAPS } from "@/lib/demo-gaps";

export default function Home() {
  // Terminal gaps never enter the inbox. The *live* count after a dismissal is
  // derived inside the workspace, not here — see AppShell's `inboxCount`.
  const open = DEMO_GAPS.filter((gap) => gap.status !== "resolved" && gap.status !== "dismissed");
  return <Workspace gaps={open} />;
}
