import { cn } from "@/lib/utils";
import { useSim } from "@/store/sim";

/** Connection state and a count of every /ws message type received, to check the seam at a glance. */
export function StatusBar({ className }: { className?: string }) {
  const connection = useSim((s) => s.connection);
  const counts = useSim((s) => s.messageCounts);
  return (
    <div className={cn("flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground", className)}>
      <span className="flex items-center gap-1.5">
        <span
          className={cn(
            "size-2 rounded-full",
            connection === "open" ? "bg-lane-with" : connection === "connecting" ? "bg-importance-deferrable" : "bg-lane-without",
          )}
        />
        /ws {connection}
      </span>
      {Object.entries(counts).map(([type, n]) => (
        <span key={type} className="tabular-nums">
          {type} {n}
        </span>
      ))}
    </div>
  );
}
