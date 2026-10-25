import type { ReactNode } from "react";
import { Gauge, Leaf, Receipt, Zap, type LucideIcon } from "lucide-react";
import { Card } from "@/components/ui/card";
import { fmtKw, fmtKwh, fmtUsd } from "@/lib/format";
import { NO_REAL_TARIFF, NO_REAL_TARIFF_HINT, useRealTariff } from "@/lib/money";
import { cn } from "@/lib/utils";
import { useDashboardStore as useSim } from "@/data";

/** Headline numbers for the `with` lane, with the `without` lane underneath for comparison. */
export function KpiRow() {
  const without = useSim((s) => s.latest.without?.meter);
  const withLane = useSim((s) => s.latest.with?.meter);
  // Lane differences come from the engine's LaneComparison; the browser never subtracts lanes (UI.md).
  const comparison = useSim((s) => s.comparison);
  const overCap = withLane ? withLane.block_avg_kw > withLane.target_kw : false;
  const realTariff = useRealTariff();

  return (
    <div className="grid grid-cols-2 gap-3 2xl:grid-cols-4">
      <Kpi icon={Zap} tone="var(--lane-with)" label="Power now" live value={fmtKw(withLane?.total_kw)} sub={`Without WattWise ${fmtKw(without?.total_kw)}`} />
      <Kpi
        icon={Gauge}
        tone={overCap ? "var(--lane-without)" : "var(--importance-flexible)"}
        label="15-min average"
        value={fmtKw(withLane?.block_avg_kw)}
        sub={`Current target ${fmtKw(withLane?.target_kw)}`}
      >
        {withLane && (
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
            {/* Bar length is only a picture of block_avg vs cap; no number is derived from it. */}
            <div
              className={cn("h-full rounded-full transition-[width]", overCap ? "bg-lane-without" : "bg-lane-with")}
              style={{ width: `${Math.min(100, (withLane.block_avg_kw / withLane.target_kw) * 100)}%` }}
            />
          </div>
        )}
      </Kpi>
      {realTariff ? (
        <Kpi
          icon={Receipt}
          tone="var(--importance-deferrable)"
          label="Bill this month"
          value={fmtUsd(withLane?.cost_usd_month)}
          sub={`Without WattWise ${fmtUsd(without?.cost_usd_month)}`}
        />
      ) : (
        <Kpi
          icon={Receipt}
          tone="var(--importance-deferrable)"
          label="Energy this month"
          value={fmtKwh(withLane?.energy_kwh_month)}
          sub={`Bill: ${NO_REAL_TARIFF.toLowerCase()}`}
          title={NO_REAL_TARIFF_HINT}
        />
      )}
      <Kpi
        icon={Leaf}
        tone="var(--lane-with)"
        label={realTariff ? "Saved today" : "Peak avoided"}
        value={realTariff ? fmtUsd(comparison?.saved_today_usd) : fmtKw(comparison?.peak_avoided_kw)}
        sub={realTariff ? `Peak avoided ${fmtKw(comparison?.peak_avoided_kw)}` : `Savings in $: ${NO_REAL_TARIFF.toLowerCase()}`}
        title={realTariff ? undefined : NO_REAL_TARIFF_HINT}
        highlight
      />
    </div>
  );
}

function Kpi({
  icon: Icon,
  tone,
  label,
  value,
  sub,
  live,
  highlight,
  title,
  children,
}: {
  icon: LucideIcon;
  tone: string;
  label: string;
  value: ReactNode;
  sub: string;
  live?: boolean;
  highlight?: boolean;
  title?: string;
  children?: ReactNode;
}) {
  return (
    <Card title={title} className={cn("flex-row items-start gap-3 px-4 py-3.5", highlight && "border-lane-with/40 bg-lane-with/[0.06]")}>
      <span
        className="flex size-10 shrink-0 items-center justify-center rounded-xl"
        style={{ background: `color-mix(in oklch, ${tone} 16%, transparent)`, color: tone }}
      >
        <Icon className="size-5" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {label}
          {live && (
            <span className="flex items-center gap-1 text-lane-with">
              <span className="size-1.5 rounded-full bg-lane-with" /> Live
            </span>
          )}
        </div>
        <div className={cn("mt-0.5 text-2xl font-semibold tracking-tight tabular-nums", highlight && "text-lane-with")}>{value}</div>
        <div className="truncate text-xs text-muted-foreground tabular-nums">{sub}</div>
        {children}
      </div>
    </Card>
  );
}
