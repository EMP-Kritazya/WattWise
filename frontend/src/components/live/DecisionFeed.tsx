import { useMemo } from "react";
import { ArrowDownToLine, Clock, Play, Power, RotateCcw, Sparkles, Undo2, type LucideIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAction } from "@/hooks/useAction";
import { useDeviceNames } from "@/hooks/useDeviceNames";
import { fmtAction, fmtKw, fmtSimTime, fmtUsd } from "@/lib/format";
import { useRealTariff } from "@/lib/money";
import { STATUS_LABEL } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { useDashboardStore as useSim, type FeedItem } from "@/data";
import { transport } from "@/transport";
import type { CommandAction, DecisionStatus } from "@/types";

const ACTION_ICON: Record<CommandAction, LucideIcon> = {
  delay: Clock,
  reduce: ArrowDownToLine,
  start: Play,
  on: Power,
  off: Power,
  restore: RotateCcw,
};

const STATUS_CLASS: Record<DecisionStatus, string> = {
  executed: "border-lane-with/40 bg-lane-with/10 text-lane-with",
  undone: "text-muted-foreground",
};

/** Engine decisions, newest first, with their explanation, effect and an Undo button. */
export function DecisionFeed() {
  const feed = useSim((s) => s.feed);
  const names = useDeviceNames();
  const items = useMemo(
    () =>
      Object.values(feed).sort(
        (a, b) => b.decision.ts.localeCompare(a.decision.ts) || b.decision.decision_id.localeCompare(a.decision.decision_id),
      ),
    [feed],
  );

  return (
    <Card className="min-w-0 gap-2 py-4">
      <CardHeader className="px-4">
        <CardTitle>What WattWise did</CardTitle>
        <CardDescription>Decided by the engine, explained by the assistant · newest first</CardDescription>
      </CardHeader>
      <CardContent className="flex max-h-80 flex-col gap-2 overflow-y-auto px-4">
        {items.length === 0 && (
          <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
            No WattWise decisions yet. The engine's decisions appear here as it makes them.
          </p>
        )}
        {items.map((item) => (
          <FeedRow key={item.decision.decision_id} item={item} name={names[item.decision.device_id] ?? item.decision.device_id} />
        ))}
      </CardContent>
    </Card>
  );
}

function FeedRow({ item, name }: { item: FeedItem; name: string }) {
  const d = item.decision;
  const upsertDecisions = useSim((s) => s.upsertDecisions);
  const realTariff = useRealTariff();
  const { run, busy, error } = useAction();
  const canUndo = d.status === "executed";
  const Icon = ACTION_ICON[d.action];
  const faded = d.status === "undone";

  return (
    <div className={cn("flex gap-3 rounded-2xl border-2 border-[#22223B] bg-[#FFF6E9] p-3 text-sm", faded && "opacity-60")}>
      <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-[#22223B] bg-[#CDEAC0] text-[#22223B]">
        <Icon className="size-4" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate font-medium">
            {fmtAction(d.action, d.value)} · {name}
          </span>
          <Badge variant="outline" className={cn("ml-auto", STATUS_CLASS[d.status])}>
            {STATUS_LABEL[d.status]}
          </Badge>
        </div>
        {item.explanation && (
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            {item.explanation_source === "ai" && (
              <Badge variant="secondary" className="mr-1.5 h-4 px-1 align-[1px] text-[10px]">
                <Sparkles /> AI
              </Badge>
            )}
            {item.explanation}
          </p>
        )}
        <div className="mt-1.5 flex items-center gap-3 text-xs tabular-nums">
          <span className="text-muted-foreground">{fmtSimTime(d.ts)}</span>
          <span>
            {fmtKw(d.effect.peak_before_kw)} → {fmtKw(d.effect.peak_after_kw)}
          </span>
          {realTariff && <span className="font-medium text-lane-with">saves {fmtUsd(d.effect.saving_usd)}</span>}
          {canUndo && (
            <Button
              variant="outline"
              size="sm"
              className="ml-auto h-6 px-2 text-xs"
              disabled={busy}
              onClick={() => run(async () => upsertDecisions([await transport.undo(d.decision_id)]))}
            >
              <Undo2 /> Undo
            </Button>
          )}
        </div>
        {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
      </div>
    </div>
  );
}
