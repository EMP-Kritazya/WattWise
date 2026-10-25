import { Link } from "react-router";
import { ContextStrip } from "@/components/live/ContextStrip";
import { DecisionFeed } from "@/components/live/DecisionFeed";
import { EscalationCard } from "@/components/live/EscalationCard";
import { KpiRow } from "@/components/live/KpiRow";
import { PowerTrendCard } from "@/components/live/LaneChart";
import { Button } from "@/components/ui/button";
import { useDashboardStore as useSim } from "@/data";

/** The owner's dashboard: headline numbers, live context, Claude's latest escalation choice, power trend and decisions. */
export function DashboardPage() {
  const kitchen = useSim((s) => s.kitchen);

  if (!kitchen) {
    return (
      <div className="mx-auto max-w-md p-12 text-center">
        <h1 className="text-xl font-semibold">No kitchen yet</h1>
        <p className="mt-2 text-muted-foreground">Build one first. The dashboard fills in once it runs.</p>
        <Button asChild className="mt-4">
          <Link to="/dashboard/builder">Open Kitchen Builder</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-4 xl:p-5">
      <KpiRow />
      <ContextStrip />
      <EscalationCard />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <PowerTrendCard />
        <DecisionFeed />
      </div>
    </div>
  );
}
