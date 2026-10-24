import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { ContextStrip } from "@/components/live/ContextStrip";
import { DecisionFeed } from "@/components/live/DecisionFeed";
import { EscalationCard } from "@/components/live/EscalationCard";
import { DevicePowerCard } from "@/components/live/DevicePowerCard";
import { LiveFloor } from "@/components/live/floor/LiveFloor";
import { KpiRow } from "@/components/live/KpiRow";
import { PowerTrendCard } from "@/components/live/LaneChart";
import { SimControls } from "@/components/live/SimControls";
import { WarningBanner } from "@/components/live/WarningBanner";
import { Button } from "@/components/ui/button";
import { useDashboardStore as useSim } from "@/data";
import { transport } from "@/transport";

/** The main demo screen: controls · KPIs · the 3D floor · charts and decisions, with the assistant docked on the right. */
export function LivePage() {
  const kitchen = useSim((s) => s.kitchen);
  const hasCatalog = useSim((s) => s.catalog != null);
  const [demo, setDemo] = useState(false);

  // Device categories (for colors and placement on the floor) come from the catalog.
  useEffect(() => {
    if (!hasCatalog) transport.getCatalog().then(useSim.getState().setCatalog, () => {});
  }, [hasCatalog]);

  // Demo mode: the floor fills the screen (and the browser goes full screen when it's allowed).
  const setDemoMode = useCallback((on: boolean) => {
    setDemo(on);
    if (on) document.documentElement.requestFullscreen?.().catch(() => {});
    else if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  }, []);
  useEffect(() => {
    const onChange = () => {
      if (!document.fullscreenElement) setDemo(false);
    };
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  if (!kitchen) {
    return (
      <div className="mx-auto max-w-md p-12 text-center">
        <h1 className="text-xl font-semibold">No kitchen yet</h1>
        <p className="mt-2 text-muted-foreground">Build one first. Both lanes start from it.</p>
        <Button asChild className="mt-4">
          <Link to="/builder">Open Kitchen Builder</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="grid items-start gap-4 p-4 xl:p-5">
      <div className="flex min-w-0 flex-col gap-4">
        <WarningBanner />
        <SimControls />
        <ContextStrip />
        <EscalationCard />
        <LiveFloor demo={demo} onDemoChange={setDemoMode} />
        <KpiRow />
        <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.3fr)_minmax(0,1fr)]">
          <DevicePowerCard />
          <PowerTrendCard />
          <div className="lg:col-span-2 2xl:col-span-1">
            <DecisionFeed />
          </div>
        </div>
      </div>
    </div>
  );
}
