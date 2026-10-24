import { cn } from "@/lib/utils";
import { useDashboardStore as useSim } from "@/data";

/** Calm connection state; raw message counts stay available as a diagnostic tooltip. */
export function StatusBar({ className }: { className?: string }) {
  const connection = useSim((s) => s.connection);
  const counts = useSim((s) => s.messageCounts);
  const detail = Object.entries(counts).map(([type, n]) => `${type} ${n}`).join(" · ");
  return (
    <div className={cn("flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground", className)} title={detail || undefined}>
      <span className="flex items-center gap-1.5 font-bold">
        <span
          className={cn(
            "size-2 rounded-full",
            connection === "open" ? "bg-lane-with" : connection === "connecting" ? "bg-importance-deferrable" : "bg-lane-without",
          )}
        />
        {connection === "open" ? "Live data connected" : connection === "connecting" ? "Connecting to live data" : "Live data offline"}
      </span>
    </div>
  );
}
