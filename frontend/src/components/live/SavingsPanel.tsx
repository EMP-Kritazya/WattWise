import type { ReactNode } from "react";
import { PiggyBank, TrendingDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { useDashboardStore as useSim } from "@/data";
import { fmtKw, fmtUsd } from "@/lib/format";
import { transport } from "@/transport";

/**
 * One slim line above the live floor: what WattWise is saving (the engine's LaneComparison) and the 15-minute demand of
 * each lane against the cap (each lane's own meter, side by side). The browser never subtracts lanes (UI.md). Month peaks
 * and bills live on Dashboard.
 */
export function SavingsPanel() {
  const comparison = useSim((s) => s.comparison);
  const latest = useSim((s) => s.latest);
  const connection = useSim((s) => s.connection);
  const withMeter = latest.with?.meter;
  const withoutMeter = latest.without?.meter;
  const over = (m?: { block_avg_kw: number; target_kw: number }) => m != null && m.block_avg_kw > m.target_kw;

  return (
    <div
      aria-label="What WattWise is saving"
      aria-live="polite"
      className="flex shrink-0 flex-wrap items-center gap-x-5 gap-y-1 border-b-2 border-[#22223B] bg-[#FFF6E9] px-4 py-2 text-[#22223B]"
    >
      <Stat icon={<PiggyBank className="size-4 text-[#167D74]" />} label="Saved today" value={fmtUsd(comparison?.saved_today_usd)} strong />
      <Stat icon={<TrendingDown className="size-4 text-[#167D74]" />} label="Peak avoided" value={fmtKw(comparison?.peak_avoided_kw)} />
      <span className="hidden h-5 w-px bg-[#22223B]/20 sm:block" />
      <span className="text-xs text-[#6B687B]">15-min demand</span>
      <Stat dot="#34d399" label="With" value={fmtKw(withMeter?.block_avg_kw)} alert={over(withMeter)} />
      <Stat dot="#f87171" label="Without" value={fmtKw(withoutMeter?.block_avg_kw)} alert={over(withoutMeter)} />
      <Stat label="Cap" value={fmtKw(withMeter?.target_kw)} />
      <span className="ml-auto text-[10px] font-extrabold tracking-[0.14em] text-[#6B687B] uppercase" role="status">
        {connection !== "open" ? "Connection lost · last readings" : !latest.with ? "Waiting for hub readings" : "Simulated"}
        {transport.kind === "mock" ? " · mock data" : ""}
      </span>
    </div>
  );
}

function Stat({ icon, dot, label, value, strong, alert }: { icon?: ReactNode; dot?: string; label: string; value: string; strong?: boolean; alert?: boolean }) {
  return (
    <span className="flex items-baseline gap-1.5 whitespace-nowrap" title={alert ? "Above the cap" : undefined}>
      {icon && <span className="self-center">{icon}</span>}
      {dot && <span className="size-2 self-center rounded-full" style={{ background: dot }} />}
      <span className="text-xs text-[#6B687B]">{label}</span>
      <span className={cn("font-['Fredoka',sans-serif] font-bold tabular-nums", strong ? "text-lg" : "text-base", alert && "text-[#C93658]")}>{value}</span>
    </span>
  );
}
