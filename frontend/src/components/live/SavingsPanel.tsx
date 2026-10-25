import type { ReactNode } from "react";
import { Gauge, PiggyBank, Receipt, TrendingDown, type LucideIcon } from "lucide-react";
import { useDashboardStore as useSim } from "@/data";
import { fmtKw, fmtUsd } from "@/lib/format";

/**
 * How much WattWise is saving, beside the live floor. Savings and peak avoided are the engine's LaneComparison; the
 * month peaks and bills are each lane's own meter, shown side by side. The browser never subtracts lanes (UI.md).
 */
export function SavingsPanel() {
  const comparison = useSim((s) => s.comparison);
  const without = useSim((s) => s.latest.without?.meter);
  const withLane = useSim((s) => s.latest.with?.meter);

  return (
    <section
      aria-label="Money saved by WattWise"
      aria-live="polite"
      className="rounded-[22px] border-2 border-[#22223B] bg-[#69C9BF] p-4 text-[#22223B] shadow-[0_5px_0_#22223B]"
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 font-['Fredoka',sans-serif] text-lg font-bold">
          <PiggyBank className="size-5" /> What WattWise is saving
        </h2>
        <span className="text-[10px] font-extrabold tracking-[0.16em] uppercase opacity-70">Simulated · not measured savings</span>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile icon={PiggyBank} label="Saved today" value={fmtUsd(comparison?.saved_today_usd)} highlight />
        <Tile icon={TrendingDown} label="Peak avoided" value={fmtKw(comparison?.peak_avoided_kw)} />
        <Tile
          icon={Gauge}
          label="Month peak"
          value={fmtKw(comparison?.month_peak_with_kw)}
          sub={<>Without WattWise {fmtKw(comparison?.month_peak_without_kw)}</>}
        />
        <Tile icon={Receipt} label="Bill this month" value={fmtUsd(withLane?.cost_usd_month)} sub={<>Without WattWise {fmtUsd(without?.cost_usd_month)}</>} />
      </div>
    </section>
  );
}

function Tile({ icon: Icon, label, value, sub, highlight }: { icon: LucideIcon; label: string; value: string; sub?: ReactNode; highlight?: boolean }) {
  return (
    <div className={highlight ? "rounded-2xl border-2 border-[#22223B] bg-white px-3 py-2.5" : "rounded-2xl bg-white/85 px-3 py-2.5"}>
      <div className="flex items-center gap-1.5 text-[10px] font-extrabold tracking-wide uppercase opacity-70">
        <Icon className="size-3.5" />
        {label}
      </div>
      <div className="mt-0.5 font-['Fredoka',sans-serif] text-2xl font-bold tabular-nums">{value}</div>
      {sub && <div className="text-xs font-semibold opacity-75 tabular-nums">{sub}</div>}
    </div>
  );
}
