import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { LiveFloor } from "@/components/live/floor/LiveFloor";
import { SavingsPanel } from "@/components/live/SavingsPanel";
import { SimControls } from "@/components/live/SimControls";
import { WarningBanner } from "@/components/live/WarningBanner";
import { Button } from "@/components/ui/button";
import { useDashboardStore as useSim } from "@/data";
import { transport } from "@/transport";

/** The Live Simulation tab: controls · what WattWise is saving · the 3D floor. The owner's numbers live on Dashboard. */
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
          <Link to="/dashboard/builder">Open Kitchen Builder</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="grid items-start gap-4 p-4 xl:p-5">
      <div className="flex min-w-0 flex-col gap-4">
        <WarningBanner />
        <SimControls />
        <SavingsPanel />
        <LiveFloor demo={demo} onDemoChange={setDemoMode} />
      </div>
    </div>
  );
}
