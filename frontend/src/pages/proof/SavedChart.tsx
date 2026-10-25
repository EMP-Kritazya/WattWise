import { useMemo } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fmtUsd } from "@/lib/format";
import { LANE_COLOR } from "@/lib/theme";
import type { BacktestMonthRow, BacktestPointRow } from "@/types";
import { buildProofChart, type LinePoint } from "./proofChart";

const AXIS_TICK = { fontSize: 11, fill: "var(--muted-foreground)" };
const GRID = "oklch(1 0 0 / 7%)";

/**
 * Mode A: dollars saved this month so far (one point per replayed day, restarting each month) on a 12-month axis, with a
 * mark at each month's end labelled with that month's saved_usd. Draws row values only (UI.md: the browser never subtracts).
 */
export function SavedChart({ points, months }: { points: BacktestPointRow[]; months: BacktestMonthRow[] }) {
  const chart = useMemo(() => buildProofChart(points, months, fmtUsd), [points, months]);

  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={chart.line} margin={{ top: 28, right: 24, bottom: 4, left: 8 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis
          dataKey="x"
          type="number"
          domain={chart.domain}
          ticks={chart.ticks}
          tickFormatter={chart.tickLabel}
          interval={0}
          tick={AXIS_TICK}
          stroke={GRID}
          allowDataOverflow
        />
        <YAxis tick={AXIS_TICK} stroke={GRID} width={64} tickFormatter={(v: number) => fmtUsd(v)} domain={["auto", "auto"]} />
        <ReferenceLine y={0} stroke="var(--muted-foreground)" strokeOpacity={0.35} />
        {Array.from({ length: chart.domain[1] - 1 }, (_, i) => (
          <ReferenceLine key={i} x={i + 1} stroke={GRID} />
        ))}
        <Tooltip
          contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
          labelStyle={{ color: "var(--muted-foreground)" }}
          content={<PointTooltip />}
        />
        <Line
          name="Saved this month so far"
          dataKey="saved"
          stroke={LANE_COLOR.with}
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
          connectNulls={false}
        />
        {chart.marks.map((m) => (
          <ReferenceDot
            key={m.month}
            x={m.x}
            y={m.saved_usd}
            r={5}
            fill={LANE_COLOR.with}
            stroke="var(--background)"
            strokeWidth={2}
            label={{ value: m.label, position: "top", fontSize: 11, fill: "var(--foreground)" }}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

function PointTooltip({ active, payload }: { active?: boolean; payload?: { payload: LinePoint }[] }) {
  const p = payload?.[0]?.payload;
  if (!active || !p || p.saved === null || !p.day) return null;
  return (
    <div className="rounded-lg border bg-popover px-3 py-2 text-xs shadow-sm">
      <div className="text-muted-foreground">{p.day}</div>
      <div className="tabular-nums">Saved this month so far: {fmtUsd(p.saved)}</div>
      {p.ytd !== null && <div className="tabular-nums text-muted-foreground">Year to date: {fmtUsd(p.ytd)}</div>}
    </div>
  );
}
