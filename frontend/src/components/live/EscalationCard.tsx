import { Bot, Clock, LoaderCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { useEscalations } from "@/data";
import { fmtKw, fmtSimTime, fmtUsd } from "@/lib/format";
import { useRealTariff } from "@/lib/money";
import { cn } from "@/lib/utils";
import type { Escalation } from "@/types";

/** Engine options, fallback and validated Claude verdict; escalation never waits for owner input. */
export function EscalationCard() {
  const [e] = useEscalations();
  return e ? <EscalationDetails escalation={e} /> : null;
}

export function EscalationDetails({ escalation: e }: { escalation: Escalation }) {
  const state = STATE[e.status];
  // $ only when the engine bills on a real tariff (lib/money); kW and the rule checks always show.
  const realTariff = useRealTariff();
  const active = e.options.find((o) => o.option_id === e.active_option_id);
  const Icon = e.status === "open" ? LoaderCircle : e.resolved_by === "claude" ? Bot : Clock;
  return (
    <section aria-live="polite" className={cn("rounded-[22px] border-2 border-[#22223B] px-4 py-3 shadow-[0_4px_0_#22223B]", state.box)}>
      <div className="flex flex-wrap items-center gap-2">
        <Icon className={cn("size-4", e.status === "open" && "animate-spin")} />
        <span className="text-xs font-medium text-muted-foreground">Escalation · {fmtSimTime(e.ts)}</span>
        <Badge variant="outline">{state.label}</Badge>
      </div>
      <p className="mt-2 text-sm">
        Forecast peak <b>{fmtKw(e.problem.forecast_peak_kw)}</b> vs target <b>{fmtKw(e.problem.target_kw)}</b> ({e.problem.reason}).
      </p>
      <p className="mt-1 text-sm"><b>In force:</b> {active?.summary ?? e.active_option_id ?? "Engine safe fallback"}</p>
      {e.explanation && <p className="mt-2 text-sm">{e.explanation} <span className="text-xs text-muted-foreground">{e.explanation_source === "ai" ? "Claude explanation" : "Engine notice"}</span></p>}
      <ol className="mt-2 space-y-1 text-xs text-muted-foreground">
        {[...e.options].sort((a, b) => a.rank - b.rank).map((option) => (
          <li key={option.option_id}>
            {option.rank}. {option.summary} · peak {fmtKw(option.projected.peak_kw)}
            {realTariff && <> · cost {fmtUsd(option.projected.cost_delta_usd)}</>} · {option.within_authority ? "Within authority" : "Outside authority"}
          </li>
        ))}
      </ol>
      {e.claude_attempts.map((attempt, index) => (
        <p className="mt-2 text-xs" key={`${attempt.ts}:${index}`}>
          Claude chose {e.options.find((o) => o.option_id === attempt.option_id)?.summary ?? attempt.option_id}: {attempt.accepted ? "accepted by the engine" : attempt.reason === "outside_authority" ? "rejected: outside authority" : "rejected: after deadline"}.
          {attempt.rationale && <> “{attempt.rationale}”</>}
        </p>
      ))}
    </section>
  );
}

const STATE: Record<Escalation["status"], { label: string; box: string }> = {
  open: { label: "Safe fallback active · Claude may choose", box: "border-importance-flexible/40 bg-importance-flexible/5" },
  resolved: { label: "Claude choice accepted", box: "border-lane-with/40 bg-lane-with/5" },
  expired_default: { label: "Deadline passed · safe fallback active", box: "border-border bg-secondary/40" },
  obsolete: { label: "Risk passed", box: "border-border bg-secondary/40" },
};
