import { ExternalLink, Pause, Play, RotateCcw, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useAction } from "@/hooks/useAction";
import { fmtSimClock } from "@/lib/format";
import { requestSurge, useDashboardStore as useSim } from "@/data";
import { transport } from "@/transport";

const SPEEDS = [1, 30, 120, 600];
/** The clock only steps while the one sim host tab (`/sim`) is connected; this window name reuses that tab if it is open. */
const SIM_HOST_WINDOW = "wattwise-sim-host";

/** Top bar: sim clock, play/pause, speed, customer surges, customers/hour now. */
export function SimControls() {
  const clock = useSim((s) => s.clock);
  const latest = useSim((s) => s.latest.with);
  const kitchenName = useSim((s) => s.kitchen?.config.name);
  const clearRun = useSim((s) => s.clearRun);
  const { run, busy, error } = useAction();

  // `clock` messages only come on play/pause/speed changes; ticks carry the current sim time.
  const simTs = latest?.ts ?? clock?.sim_ts;
  const playing = clock?.playing ?? false;
  // Playing but held by the hub: say why instead of "Running", which is what made Play look broken.
  const hostOffline = clock?.paused_reason === "sim_host_offline";
  const status = !playing
    ? "Paused"
    : hostOffline
      ? "Waiting for the simulation host"
      : clock?.paused_reason === "hub_waiting"
        ? "Starting the simulation…"
        : `Running ${clock?.speed}×`;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-3 rounded-[22px] border-2 border-[#22223B] bg-white px-4 py-3 shadow-[0_5px_0_#22223B]">
      <div className="mr-auto min-w-40">
        <div className="text-xs text-muted-foreground">{kitchenName ?? "Kitchen"} · simulated time</div>
        <div className="flex items-baseline gap-2">
          <span className="text-xl font-semibold tabular-nums">{simTs ? fmtSimClock(simTs) : "–"}</span>
          <span className={hostOffline && playing ? "text-xs font-bold text-[#C93658]" : "text-xs text-muted-foreground"} role="status">
            {status}
          </span>
        </div>
      </div>

      <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:flex-nowrap">
        <Button size="sm" className="w-24" disabled={busy} onClick={() => run(() => transport.simControl({ action: playing ? "pause" : "play" }))}>
          {playing ? <Pause /> : <Play />}
          {playing ? "Pause" : "Play"}
        </Button>
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          className="order-3 w-full sm:order-none sm:w-fit"
          value={String(clock?.speed ?? 120)}
          onValueChange={(v) => v && run(() => transport.simControl({ action: playing ? "play" : "pause", speed: Number(v) }))}
        >
          {SPEEDS.map((s) => (
            <ToggleGroupItem key={s} value={String(s)} className="px-2 sm:px-2.5">
              {s}×
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <Button
          variant="ghost"
          size="icon"
          className="size-8"
          aria-label="Reset the run"
          title="Reset the run"
          disabled={busy}
          onClick={() =>
            run(async () => {
              await transport.simControl({ action: "reset" });
              clearRun();
            })
          }
        >
          <RotateCcw />
        </Button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="flex items-center gap-1.5 rounded-xl border-2 border-[#22223B] bg-[#FFF0BA] px-2.5 py-1.5 text-sm font-bold tabular-nums" title="Customers per hour (simulated)">
          <Users className="size-4 text-muted-foreground" />
          {latest?.customers_per_hour ?? "–"}
          <span className="text-xs text-muted-foreground">/ h</span>
        </span>
        <Button size="sm" variant="outline" onClick={() => run(() => requestSurge(20))}>
          +20 customers
        </Button>
        <Button size="sm" variant="outline" onClick={() => run(() => requestSurge(40))}>
          +40 customers
        </Button>
      </div>
      {hostOffline && (
        <div className="flex w-full flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border-2 border-dashed border-[#C93658] bg-[#FFF1F2] px-3 py-2 text-sm">
          <span className="font-semibold">
            The kitchen runs in a separate simulation host tab. Open it and keep it open; the clock starts as soon as it connects.
          </span>
          <Button size="sm" variant="outline" className="ml-auto" onClick={() => window.open("/sim", SIM_HOST_WINDOW)}>
            <ExternalLink /> Open simulation host
          </Button>
        </div>
      )}
      {error && <p className="w-full text-sm text-destructive">{error}</p>}
    </div>
  );
}
