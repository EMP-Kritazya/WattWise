import { TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useDashboardStore as useSim } from "@/data";

/**
 * Active warnings (cap_unreachable, hub_offline, live_transport_down, store_down), one line each.
 * CONTRACTS.md has no "warning cleared" message, so the owner dismisses them.
 */
export function WarningBanner() {
  const warnings = useSim((s) => s.warnings);
  const dismissWarning = useSim((s) => s.dismissWarning);
  const list = Object.values(warnings);
  if (!list.length) return null;
  return (
    <div className="flex flex-col gap-2">
      {list.map((w) => (
        <div
          key={w.code}
          role="alert"
          className="flex items-start gap-3 rounded-2xl border-2 border-[#22223B] bg-[#FFF0BA] px-4 py-3 text-sm shadow-[0_3px_0_#22223B]"
        >
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-importance-deferrable" />
          <p className="flex-1">{w.message}</p>
          <Button variant="ghost" size="sm" className="h-7" onClick={() => dismissWarning(w.code)}>
            Dismiss
          </Button>
        </div>
      ))}
    </div>
  );
}
