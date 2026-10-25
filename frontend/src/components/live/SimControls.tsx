import { Pause, Play, RotateCcw, Users } from "lucide-react";
import { ChatDrawer } from "@/components/ChatDrawer";
import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useAction } from "@/hooks/useAction";
import { fmtSimClock } from "@/lib/format";
import { cn } from "@/lib/utils";
import { requestSurge, useDashboardStore as useSim } from "@/data";
import { transport } from "@/transport";

const SPEEDS = [1, 30, 120, 600];

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
  const waiting = clock?.paused_reason === "escalation";

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-3 rounded-xl border bg-card px-4 py-3">
      <div className="mr-auto min-w-40">
        <div className="text-xs text-muted-foreground">{kitchenName ?? "Kitchen"} · simulated time</div>
        <div className="flex items-baseline gap-2">
          <span className="text-xl font-semibold tabular-nums">{simTs ? fmtSimClock(simTs) : "–"}</span>
          <span className={cn("text-xs", waiting ? "text-importance-deferrable" : "text-muted-foreground")}>
            {waiting ? "Paused — waiting for you" : playing ? `Running ${clock?.speed}×` : "Paused"}
          </span>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <Button size="sm" className="w-24" disabled={busy || waiting} onClick={() => run(() => transport.simControl({ action: playing ? "pause" : "play" }))}>
          {playing ? <Pause /> : <Play />}
          {playing ? "Pause" : "Play"}
        </Button>
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          value={String(clock?.speed ?? 120)}
          onValueChange={(v) => v && run(() => transport.simControl({ action: playing ? "play" : "pause", speed: Number(v) }))}
        >
          {SPEEDS.map((s) => (
            <ToggleGroupItem key={s} value={String(s)} className="px-2.5">
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
        <span className="flex items-center gap-1.5 rounded-lg bg-secondary px-2.5 py-1.5 text-sm tabular-nums" title="Customers per hour (simulated)">
          <Users className="size-4 text-muted-foreground" />
          {latest?.customers_per_hour ?? "–"}
          <span className="text-xs text-muted-foreground">/ h</span>
        </span>
        <Button size="sm" variant="outline" onClick={() => run(() => requestSurge(20))}>
          +20 customers
        </Button>
        <Button size="sm" onClick={() => run(() => requestSurge(40))}>
          +40 customers
        </Button>
        {/* The assistant is no longer docked on the Live page, so this is its entry point at every width. */}
        <ChatDrawer />
      </div>
      {error && <p className="w-full text-sm text-destructive">{error}</p>}
    </div>
  );
}
