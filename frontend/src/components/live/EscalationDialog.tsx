import { useMemo } from "react";
import { ShieldAlert, ShieldCheck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useEscalations, useLive as useSim } from "@/data";
import { useAction } from "@/hooks/useAction";
import { fmtKw, fmtSimTime, fmtUsd } from "@/lib/format";
import { cn } from "@/lib/utils";
import { transport } from "@/transport";
import type { EscalationOption } from "@/types";

/**
 * An escalation that Claude couldn't settle within the owner's authority: the owner picks one of the engine's options.
 * Every number shown comes from the engine (problem, projected peak, cost, rule breaks).
 * Phase 3 adds the inline escalation card with the "Claude is choosing…" / "Claude chose X" states.
 */
export function EscalationDialog() {
  const escalations = useEscalations();
  const clock = useSim((s) => s.clock);
  const upsertEscalations = useSim((s) => s.upsertEscalations);
  const { run, busy, error } = useAction();
  const e = useMemo(() => escalations.find((x) => x.status === "awaiting_owner"), [escalations]);

  if (!e) return null;
  const choose = (optionId: string) => run(async () => upsertEscalations([await transport.resolveEscalation(e.escalation_id, optionId)]));
  const paused = clock?.paused_reason === "escalation";

  return (
    <Dialog open>
      <DialogContent className="sm:max-w-xl" showCloseButton={false} onEscapeKeyDown={(ev) => ev.preventDefault()} onInteractOutside={(ev) => ev.preventDefault()}>
        <DialogHeader>
          <DialogTitle>WattWise needs your decision</DialogTitle>
          <DialogDescription>
            The forecast peak is {fmtKw(e.problem.forecast_peak_kw)} against your {fmtKw(e.problem.target_kw)} cap ({e.problem.reason}).
            {e.rationale && <> Claude: “{e.rationale}”</>}
            {paused ? " The clock is paused until you choose." : ` If you don't choose by ${fmtSimTime(e.deadline_sim_ts)}, the default applies.`}
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-2">
          {e.options.map((o) => (
            <OptionRow key={o.option_id} option={o} isDefault={o.option_id === e.default_option_id} disabled={busy} onChoose={() => choose(o.option_id)} />
          ))}
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
      </DialogContent>
    </Dialog>
  );
}

function OptionRow({ option: o, isDefault, disabled, onChoose }: { option: EscalationOption; isDefault: boolean; disabled: boolean; onChoose: () => void }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border bg-secondary/40 p-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
          {o.summary}
          {isDefault && <Badge variant="outline">default</Badge>}
          <Badge variant="outline" className={cn(o.within_authority ? "border-lane-with/40 text-lane-with" : "border-importance-deferrable/40 text-importance-deferrable")}>
            {o.within_authority ? <ShieldCheck /> : <ShieldAlert />}
            {o.within_authority ? "within Claude's authority" : "outside Claude's authority"}
          </Badge>
        </div>
        <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-muted-foreground tabular-nums">
          {o.projected && (
            <>
              <span>Peak {fmtKw(o.projected.peak_kw)}</span>
              <span>Cost {fmtUsd(o.projected.cost_delta_usd)}</span>
              {o.projected.max_indoor_temp_change_c > 0 && <span>Room +{o.projected.max_indoor_temp_change_c.toFixed(1)} °C</span>}
            </>
          )}
          {o.rule_breaks.map((b, i) => (
            <span key={i} className="text-importance-deferrable">
              Breaks: {b.kind.replaceAll("_", " ")} {b.amount} {b.unit}
              {b.device_id ? ` (${b.device_id})` : ""}
            </span>
          ))}
        </div>
      </div>
      <Button size="sm" variant={o.option_id === "ask_owner" ? "ghost" : "default"} disabled={disabled || o.option_id === "ask_owner"} onClick={onChoose}>
        Choose
      </Button>
    </div>
  );
}
