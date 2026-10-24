import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { fmtKw, fmtSimTime } from "@/lib/format";
import { LANE_COLOR, LANE_LABEL } from "@/lib/theme";
import { useLive as useSim } from "@/data";

const BLOCK_MS = 15 * 60_000;
const AXIS_TICK = { fontSize: 11, fill: "var(--muted-foreground)" };
const GRID = "oklch(1 0 0 / 7%)";
const TOOLTIP = {
  contentStyle: { background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 },
  labelStyle: { color: "var(--muted-foreground)" },
};

interface Row {
  t: number;
  without?: number;
  with?: number;
  forecast?: number;
}

/** Both lanes over time: the last 3 sim hours as lines, or today's 15-minute demand blocks as bars. */
export function PowerTrendCard() {
  const [view, setView] = useState<"lines" | "blocks">("lines");
  return (
    <Card className="min-w-0 gap-2 py-4">
      <CardHeader className="px-4">
        <CardTitle>Without vs with WattWise</CardTitle>
        <CardDescription>{view === "lines" ? "Total kW, last 3 sim hours + 2 h forecast" : "15-minute averages today: the highest one sets the demand charge"} · simulated</CardDescription>
        <ToggleGroup
          type="single"
          variant="outline"
          size="sm"
          className="mt-1"
          value={view}
          onValueChange={(v) => v && setView(v as "lines" | "blocks")}
        >
          <ToggleGroupItem value="lines" className="px-3">
            Last 3 h
          </ToggleGroupItem>
          <ToggleGroupItem value="blocks" className="px-3">
            15-min blocks
          </ToggleGroupItem>
        </ToggleGroup>
      </CardHeader>
      <CardContent className="h-64 px-2">{view === "lines" ? <LanesLines /> : <DemandBlocks />}</CardContent>
    </Card>
  );
}

function LanesLines() {
  const history = useSim((s) => s.history);
  const forecast = useSim((s) => s.forecast);
  const withMeter = useSim((s) => s.latest.with?.meter);
  const withoutMeter = useSim((s) => s.latest.without?.meter);

  const data = useMemo(() => {
    const rows = new Map<number, Row>();
    const row = (t: number) => rows.get(t) ?? rows.set(t, { t }).get(t)!;
    for (const p of history.without) row(p.t).without = p.total_kw;
    for (const p of history.with) row(p.t).with = p.total_kw;
    if (forecast) {
      // UNCLEAR in CONTRACTS.md: where forecast_kw starts. Assumed: block k covers from_ts + k×15 min,
      // drawn at the block's midpoint and joined to the `with` reading at from_ts.
      const from = Date.parse(forecast.from_ts);
      const start = rows.get(from);
      if (start?.with != null) start.forecast = start.with;
      forecast.kw.forEach((kw, k) => {
        row(from + (k + 0.5) * BLOCK_MS).forecast = kw;
      });
    }
    return [...rows.values()].sort((a, b) => a.t - b.t);
  }, [history, forecast]);

  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis
          dataKey="t"
          type="number"
          scale="time"
          domain={["dataMin", "dataMax"]}
          tickFormatter={(t: number) => fmtSimTime(t)}
          tick={AXIS_TICK}
          stroke={GRID}
          minTickGap={40}
        />
        <YAxis tick={AXIS_TICK} stroke={GRID} width={36} domain={[0, "auto"]} />
        <Tooltip {...TOOLTIP} labelFormatter={(t) => fmtSimTime(Number(t))} formatter={(v) => fmtKw(Number(v))} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {withMeter && (
          <ReferenceLine
            y={withMeter.peak_cap_kw}
            stroke="var(--cap-line)"
            strokeDasharray="6 4"
            label={{ value: `Peak cap ${fmtKw(withMeter.peak_cap_kw)}`, position: "insideTopLeft", fontSize: 11, fill: "var(--cap-line)" }}
          />
        )}
        {withoutMeter && <ReferenceLine y={withoutMeter.month_peak_kw} stroke={LANE_COLOR.without} strokeOpacity={0.4} />}
        {withMeter && <ReferenceLine y={withMeter.month_peak_kw} stroke={LANE_COLOR.with} strokeOpacity={0.4} />}
        <Line name={`${LANE_LABEL.without} (simulated)`} dataKey="without" stroke={LANE_COLOR.without} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
        <Line name={`${LANE_LABEL.with} (simulated)`} dataKey="with" stroke={LANE_COLOR.with} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
        <Line name="Forecast (simulated)" dataKey="forecast" stroke={LANE_COLOR.with} strokeDasharray="5 4" dot={false} isAnimationActive={false} connectNulls />
      </LineChart>
    </ResponsiveContainer>
  );
}

function DemandBlocks() {
  const blocks = useSim((s) => s.blocks);
  const cap = useSim((s) => s.latest.with?.meter.peak_cap_kw);

  const data = useMemo(() => {
    const rows = new Map<number, Row>();
    const row = (t: number) => rows.get(t) ?? rows.set(t, { t }).get(t)!;
    for (const b of blocks.without) row(b.start).without = b.avg_kw;
    for (const b of blocks.with) row(b.start).with = b.avg_kw;
    return [...rows.values()].sort((a, b) => a.t - b.t);
  }, [blocks]);

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }} barGap={1} barCategoryGap="18%">
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="t" tickFormatter={(t: number) => fmtSimTime(t)} tick={AXIS_TICK} stroke={GRID} minTickGap={30} />
        <YAxis tick={AXIS_TICK} stroke={GRID} width={36} domain={[0, "auto"]} />
        <Tooltip {...TOOLTIP} cursor={{ fill: "oklch(1 0 0 / 5%)" }} labelFormatter={(t) => `Block from ${fmtSimTime(Number(t))}`} formatter={(v) => fmtKw(Number(v))} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {cap != null && (
          <ReferenceLine
            y={cap}
            stroke="var(--cap-line)"
            strokeDasharray="6 4"
            label={{ value: `Peak cap ${fmtKw(cap)}`, position: "insideTopLeft", fontSize: 11, fill: "var(--cap-line)" }}
          />
        )}
        <Bar name={`${LANE_LABEL.without} (simulated)`} dataKey="without" fill={LANE_COLOR.without} radius={[3, 3, 0, 0]} isAnimationActive={false} />
        <Bar name={`${LANE_LABEL.with} (simulated)`} dataKey="with" fill={LANE_COLOR.with} radius={[3, 3, 0, 0]} isAnimationActive={false} />
      </BarChart>
    </ResponsiveContainer>
  );
}
