import { Dashboard } from "@/components/Dashboard";
import { DEMO_GAPS } from "@/lib/demo-gaps";

export default function Home() {
  const open = DEMO_GAPS.filter((gap) => gap.status !== "resolved" && gap.status !== "dismissed");
  return <Dashboard gaps={open} />;
}
