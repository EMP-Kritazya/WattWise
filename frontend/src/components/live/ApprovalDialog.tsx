import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useAction } from "@/hooks/useAction";
import { useDeviceNames } from "@/hooks/useDeviceNames";
import { fmtAction, fmtKw, fmtSimTime, fmtUsd } from "@/lib/format";
import { useSim } from "@/store/sim";
import { transport } from "@/transport";

/** A move outside the owner's limits waits here for Approve / Decline. */
export function ApprovalDialog() {
  const approval = useSim((s) => s.approval);
  const clock = useSim((s) => s.clock);
  const upsertDecisions = useSim((s) => s.upsertDecisions);
  const names = useDeviceNames();
  const { run, busy, error } = useAction();

  if (!approval) return null;
  const d = approval.decision;
  const answer = (approve: boolean) => run(async () => upsertDecisions([await transport.approve(d.decision_id, approve)]));
  const paused = clock?.paused_reason === "awaiting_approval";

  return (
    <Dialog open>
      <DialogContent showCloseButton={false} onEscapeKeyDown={(e) => e.preventDefault()} onInteractOutside={(e) => e.preventDefault()}>
        <DialogHeader>
          <DialogTitle>Approve this change?</DialogTitle>
          <DialogDescription>
            It goes beyond the limits you set, so WattWise needs your OK.
            {paused ? " The clock is paused until you answer." : ` It expires at ${fmtSimTime(approval.expires_at)}.`}
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3 text-sm">
          <div className="text-base font-medium">
            {names[d.device_id] ?? d.device_id}: {fmtAction(d.action, d.value)}
          </div>
          <p className="text-muted-foreground">{approval.explanation}</p>
          <div className="flex gap-4 tabular-nums">
            <span>
              Peak {fmtKw(d.effect.peak_before_kw)} → {fmtKw(d.effect.peak_after_kw)}
            </span>
            <span>Saves {fmtUsd(d.effect.saving_usd)}</span>
          </div>
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <DialogFooter>
          <Button variant="outline" size="lg" disabled={busy} onClick={() => answer(false)}>
            Decline
          </Button>
          <Button size="lg" disabled={busy} onClick={() => answer(true)}>
            Approve
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
