import { TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useSim } from "@/store/sim";

/** e.g. cap_unreachable. CONTRACTS.md has no "warning cleared" message yet, so the owner dismisses it. */
export function WarningBanner() {
  const warning = useSim((s) => s.warning);
  const dismissWarning = useSim((s) => s.dismissWarning);
  if (!warning) return null;
  return (
    <div role="alert" className="flex items-start gap-3 rounded-lg border border-importance-deferrable/40 bg-importance-deferrable/10 px-4 py-3 text-sm">
      <TriangleAlert className="mt-0.5 size-4 shrink-0 text-importance-deferrable" />
      <p className="flex-1">{warning.message}</p>
      <Button variant="ghost" size="sm" className="h-7" onClick={dismissWarning}>
        Dismiss
      </Button>
    </div>
  );
}
