import { useEffect, useMemo, useState } from "react";
import { ArrowDownToLine, Clock, Minimize2, Pause, Play, Power, RotateCcw, Sparkles, Users, type LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAction } from "@/hooks/useAction";
import { useDeviceNames } from "@/hooks/useDeviceNames";
import { fmtAction, fmtKw, fmtSimClock, fmtUsd } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useSim, type FeedItem } from "@/store/sim";
import { transport } from "@/transport";
import type { CommandAction } from "@/types";
import { LANE_HEX } from "./palette";

const GLASS = "rounded-xl border border-white/10 bg-[#0f1424]/80 shadow-2xl backdrop-blur-md";

// ---------- peak meter ----------

/** The demand-charge story in one glance: each lane's 15-minute average against the cap. */
export function PeakMeter({ className }: { className?: string }) {
  const without = useSim((s) => s.latest.without?.meter);
  const withLane = useSim((s) => s.latest.with?.meter);
  if (!without || !withLane) return null;
  const cap = withLane.peak_cap_kw;
  // Bar lengths only draw the meter values against the cap; no number shown is derived from them.
  const scale = Math.max(cap * 1.35, without.block_avg_kw, withLane.block_avg_kw);
  return (
    <div className={cn(GLASS, "w-60 p-3 sm:w-72 sm:p-3.5", className)}>
      <div className="text-sm font-semibold">15-minute average vs your cap</div>
      <div className="hidden text-[11px] text-white/50 sm:block">The highest one this month sets the demand charge</div>
      <MeterRow label="Without WattWise" value={without.block_avg_kw} cap={cap} scale={scale} color={LANE_HEX.without} />
      <MeterRow label="With WattWise" value={withLane.block_avg_kw} cap={cap} scale={scale} color={LANE_HEX.with} />
      <div className="mt-3 flex items-center justify-between border-t border-white/10 pt-2 text-[11px] text-white/55 tabular-nums">
        <span>Cap {fmtKw(cap)}</span>
        <span>
          Month peak <span style={{ color: LANE_HEX.without }}>{fmtKw(without.month_peak_kw)}</span> vs{" "}
          <span style={{ color: LANE_HEX.with }}>{fmtKw(withLane.month_peak_kw)}</span>
        </span>
      </div>
    </div>
  );
}

function MeterRow({ label, value, cap, scale, color }: { label: string; value: number; cap: number; scale: number; color: string }) {
  const over = value > cap;
  return (
    <div className="mt-3">
      <div className="flex items-baseline justify-between text-xs">
        <span className="text-white/75">{label}</span>
        <span className={cn("font-semibold tabular-nums", over ? "text-red-300" : "text-white")}>
          {fmtKw(value)}
          {over && <span className="ml-1 animate-pulse text-[10px] font-bold tracking-wide text-red-400">OVER CAP</span>}
        </span>
      </div>
      <div className="relative mt-1.5 h-2.5 rounded-full bg-white/10">
        <div
          className="h-full rounded-full transition-[width] duration-300"
          style={{ width: `${Math.min(100, (value / scale) * 100)}%`, background: over ? "#ef4444" : color, boxShadow: `0 0 12px ${over ? "#ef4444" : color}` }}
        />
        <div className="absolute -top-1 h-[18px] w-0.5 rounded bg-white/85" style={{ left: `${(cap / scale) * 100}%` }} />
      </div>
    </div>
  );
}

// ---------- newest decision ----------

const ACTION_ICON: Record<CommandAction, LucideIcon> = {
  delay: Clock,
  reduce: ArrowDownToLine,
  start: Play,
  on: Power,
  off: Power,
  restore: RotateCcw,
};

/** The latest thing WattWise did, slid in for a few seconds with its explanation. */
export function DecisionToast({ className }: { className?: string }) {
  const feed = useSim((s) => s.feed);
  const names = useDeviceNames();
  const newest = useMemo(() => newestDecision(feed), [feed]);
  const [shownId, setShownId] = useState<string | null>(null);
  const id = newest?.decision.decision_id;

  useEffect(() => {
    if (!id) return;
    setShownId(id);
    const t = setTimeout(() => setShownId(null), 8000);
    return () => clearTimeout(t);
  }, [id]);

  if (!newest || shownId !== id) return null;
  const d = newest.decision;
  const Icon = ACTION_ICON[d.action];
  const waiting = d.status === "awaiting_approval";
  return (
    <div key={id} className={cn(GLASS, "w-[380px] max-w-full p-3.5 animate-in fade-in slide-in-from-bottom-4 duration-500", className)}>
      <div className="flex items-start gap-3">
        <span
          className={cn(
            "flex size-9 shrink-0 items-center justify-center rounded-lg",
            waiting ? "bg-amber-400/15 text-amber-300" : "bg-blue-400/15 text-blue-300",
          )}
        >
          <Icon className="size-4.5" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[11px] font-medium tracking-wide text-white/50 uppercase">{waiting ? "Needs your OK" : "WattWise just acted"}</div>
          <div className="text-sm font-semibold">
            {fmtAction(d.action, d.value)} · {names[d.device_id] ?? d.device_id}
          </div>
          {newest.explanation && (
            <p className="mt-1 text-xs leading-relaxed text-white/70">
              {newest.explanation_source === "ai" && (
                <span className="mr-1 inline-flex items-center gap-0.5 rounded bg-white/10 px-1 text-[10px] text-white/80">
                  <Sparkles className="size-2.5" /> AI
                </span>
              )}
              {newest.explanation}
            </p>
          )}
          <div className="mt-1.5 flex gap-3 text-xs tabular-nums">
            <span className="text-white/60">
              {fmtKw(d.effect.peak_before_kw)} → {fmtKw(d.effect.peak_after_kw)}
            </span>
            <span className="font-semibold text-emerald-300">saves {fmtUsd(d.effect.saving_usd)}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export function newestDecision(feed: Record<string, FeedItem>): FeedItem | null {
  let best: FeedItem | null = null;
  for (const item of Object.values(feed)) {
    const s = item.decision.status;
    if (s !== "executed" && s !== "approved" && s !== "awaiting_approval") continue;
    if (!best || item.decision.ts > best.decision.ts || (item.decision.ts === best.decision.ts && item.decision.decision_id > best.decision.decision_id)) {
      best = item;
    }
  }
  return best;
}

// ---------- demo bar (full-screen mode) ----------

/** Everything the presenter needs on one bar: clock, play, customer surges, money saved, exit. */
export function DemoBar({ onExit }: { onExit: () => void }) {
  const clock = useSim((s) => s.clock);
  const latest = useSim((s) => s.latest.with);
  const without = useSim((s) => s.latest.without?.meter);
  const { run, busy } = useAction();
  const simTs = latest?.ts ?? clock?.sim_ts;
  const playing = clock?.playing ?? false;
  const waiting = clock?.paused_reason === "awaiting_approval";
  // The one calculation the UI is allowed (UI.md): saved today = without cost − with cost.
  const saved = without && latest ? without.cost_usd_today - latest.meter.cost_usd_today : null;

  return (
    <div className={cn(GLASS, "flex flex-wrap items-center gap-3 px-3 py-2")}>
      <div className="px-1">
        <div className="text-lg leading-tight font-semibold tabular-nums">{simTs ? fmtSimClock(simTs) : "–"}</div>
        <div className={cn("text-[11px]", waiting ? "text-amber-300" : "text-white/50")}>
          {waiting ? "Paused — waiting for you" : playing ? `Running ${clock?.speed}×` : "Paused"}
        </div>
      </div>
      <Button size="sm" disabled={busy || waiting} onClick={() => run(() => transport.simControl({ action: playing ? "pause" : "play" }))}>
        {playing ? <Pause /> : <Play />}
        {playing ? "Pause" : "Play"}
      </Button>
      <span className="flex items-center gap-1.5 rounded-lg bg-white/5 px-2.5 py-1.5 text-sm tabular-nums">
        <Users className="size-4 text-white/50" />
        {latest?.customers_per_hour ?? "–"}
        <span className="text-xs text-white/50">/ h</span>
      </span>
      <Button size="sm" variant="outline" onClick={() => run(() => transport.addCustomers({ customers: 20, duration_min: 60 }))}>
        +20 customers
      </Button>
      <Button size="sm" className="bg-amber-400 text-amber-950 hover:bg-amber-300" onClick={() => run(() => transport.addCustomers({ customers: 40, duration_min: 60 }))}>
        +40 customers
      </Button>
      <div className="px-2 text-right">
        <div className="text-[11px] text-white/50">Saved today</div>
        <div className="text-lg leading-tight font-semibold text-emerald-300 tabular-nums">{fmtUsd(saved)}</div>
      </div>
      <Button size="icon" variant="ghost" className="size-8" aria-label="Exit demo mode" title="Exit demo mode (Esc)" onClick={onExit}>
        <Minimize2 />
      </Button>
    </div>
  );
}
