import { Bot, CheckCircle2, Clock, LoaderCircle, User } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { useEscalations } from "@/data";
import { fmtKw, fmtSimTime, fmtUsd } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Escalation } from "@/types";

/**
 * The latest escalation, inline on the Live screen (UI.md): the problem in engine numbers, then
 * Claude is choosing… → Claude chose X: rationale · Default applied. The owner is never asked (full authority): an
 * `awaiting_owner` row shows Claude's pick and when the engine's default applies, never a question to the owner.
 */
export function EscalationCard() {
  const [latest] = useEscalations();
  if (!latest) return null;
  const e = latest;
  const chosen = e.options.find((o) => o.option_id === e.chosen_option_id);
  const state = STATE[e.status];
  const Icon = e.status === "open" ? LoaderCircle : e.resolved_by === "owner" ? User : e.resolved_by === "claude" ? Bot : Clock;

  return (
    <section
      aria-live="polite"
      className={cn("flex flex-wrap items-start gap-4 rounded-[22px] border-2 border-[#22223B] px-4 py-3 shadow-[0_4px_0_#22223B]", state.box)}
    >
      <span className={cn("flex size-10 shrink-0 items-center justify-center rounded-xl", state.icon)}>
        <Icon className={cn("size-5", e.status === "open" && "animate-spin")} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Escalation · {fmtSimTime(e.ts || e.block_start || new Date().toISOString())}</span>
          <Badge variant="outline" className={state.badge}>
            {state.label(e)}
          </Badge>
        </div>
        <div className="mt-1 text-sm">
          Forecast peak <b className="tabular-nums">{fmtKw(e.problem.forecast_peak_kw)}</b> vs cap{" "}
          <b className="tabular-nums">{fmtKw(e.problem.target_kw)}</b> ({e.problem.reason}). Routine moves weren't enough, so WattWise
          offered {e.options.length} options.
        </div>
        {chosen && (
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            <CheckCircle2 className="size-4 text-lane-with" />
            <span className="font-medium">{chosen.summary}</span>
            {chosen.projected && (
              <span className="text-xs text-muted-foreground tabular-nums">
                peak {fmtKw(chosen.projected.peak_kw)} · cost {fmtUsd(chosen.projected.cost_delta_usd)}
              </span>
            )}
          </div>
        )}
        {e.rationale && (
          <p className="mt-1 text-xs text-muted-foreground">
            Claude: “{e.rationale}”
          </p>
        )}
        {e.status === "awaiting_owner" && e.deadline_sim_ts && (
          <p className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
            <Clock className="size-3.5" /> Engine default applies at {fmtSimTime(e.deadline_sim_ts)}
          </p>
        )}
      </div>
    </section>
  );
}

const STATE: Record<Escalation["status"], { label: (e: Escalation) => string; box: string; icon: string; badge: string }> = {
  open: {
    label: () => "Claude is choosing…",
    box: "border-importance-flexible/40 bg-importance-flexible/5",
    icon: "bg-importance-flexible/15 text-importance-flexible",
    badge: "border-importance-flexible/40 text-importance-flexible",
  },
  // Not a question to the owner: Claude has picked and the engine's default holds until the deadline.
  awaiting_owner: {
    label: () => "Claude chose",
    box: "border-lane-with/40 bg-lane-with/5",
    icon: "bg-lane-with/15 text-lane-with",
    badge: "border-lane-with/40 text-lane-with",
  },
  resolved: {
    label: (e) => (e.resolved_by === "claude" ? "Claude chose" : e.resolved_by === "owner" ? "You chose" : "Resolved"),
    box: "border-lane-with/40 bg-lane-with/5",
    icon: "bg-lane-with/15 text-lane-with",
    badge: "border-lane-with/40 text-lane-with",
  },
  expired_default: {
    label: () => "Default applied",
    box: "border-border bg-secondary/40",
    icon: "bg-muted text-muted-foreground",
    badge: "text-muted-foreground",
  },
};
