import type { ReactNode } from "react";
import { Gauge, Leaf, Receipt, Zap, type LucideIcon } from "lucide-react";
import { Card } from "@/components/ui/card";
import { fmtKw, fmtUsd } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useLive as useSim } from "@/data";

/** Headline numbers for the `with` lane, with the `without` lane underneath for comparison. */
export function KpiRow() {
  const without = useSim((s) => s.latest.without?.meter);
  const withLane = useSim((s) => s.latest.with?.meter);
  // Lane differences come from the engine's LaneComparison; the browser never subtracts lanes (UI.md).
  const comparison = useSim((s) => s.comparison);
  const overCap = withLane ? withLane.block_avg_kw > withLane.peak_cap_kw : false;

  return (
    <div className="grid grid-cols-2 gap-3 2xl:grid-cols-4">
      <Kpi icon={Zap} tone="var(--lane-with)" label="Power now" live value={fmtKw(withLane?.total_kw)} sub={`Without WattWise ${fmtKw(without?.total_kw)}`} />
      <Kpi
        icon={Gauge}
        tone={overCap ? "var(--lane-without)" : "var(--importance-flexible)"}
        label="15-min average"
        value={fmtKw(withLane?.block_avg_kw)}
        sub={`Peak cap ${fmtKw(withLane?.peak_cap_kw)}`}
      >
        {withLane && (
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
            {/* Bar length is only a picture of block_avg vs cap; no number is derived from it. */}
            <div
              className={cn("h-full rounded-full transition-[width]", overCap ? "bg-lane-without" : "bg-lane-with")}
              style={{ width: `${Math.min(100, (withLane.block_avg_kw / withLane.peak_cap_kw) * 100)}%` }}
            />
          </div>
        )}
      </Kpi>
      <Kpi
        icon={Receipt}
        tone="var(--importance-deferrable)"
        label="Bill this month"
        value={fmtUsd(withLane?.cost_usd_month)}
        sub={`Without WattWise ${fmtUsd(without?.cost_usd_month)}`}
      />
      <Kpi
        icon={Leaf}
        tone="var(--lane-with)"
        label="Saved today"
        value={fmtUsd(comparison?.saved_today_usd)}
        sub={`Peak avoided ${fmtKw(comparison?.peak_avoided_kw)}`}
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
  children,
}: {
  icon: LucideIcon;
  tone: string;
  label: string;
  value: ReactNode;
  sub: string;
  live?: boolean;
  highlight?: boolean;
  children?: ReactNode;
}) {
  return (
    <Card className={cn("flex-row items-start gap-3 px-4 py-3.5", highlight && "border-lane-with/40 bg-lane-with/[0.06]")}>
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
              <span className="size-1.5 animate-pulse rounded-full bg-lane-with" /> Live
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
