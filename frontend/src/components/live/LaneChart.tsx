import { useMemo } from "react";
import {
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
import { fmtKw, fmtSimTime } from "@/lib/format";
import { LANE_COLOR, LANE_LABEL } from "@/lib/theme";
import { useDashboardStore as useSim } from "@/data";

const BLOCK_MS = 15 * 60_000;
const AXIS_TICK = { fontSize: 11, fill: "var(--muted-foreground)" };
const GRID = "rgb(34 34 59 / 14%)";
const TOOLTIP = {
  contentStyle: { background: "var(--popover)", border: "2px solid var(--border)", borderRadius: 14, fontSize: 12, boxShadow: "0 3px 0 #22223B" },
  labelStyle: { color: "var(--muted-foreground)" },
};

interface Row {
  t: number;
  without?: number;
  with?: number;
  forecast?: number;
}

/** Both lanes over the last 3 sim hours, with the cap, each lane's month peak and the forecast (UI.md two-lane chart). */
export function PowerTrendCard() {
  return (
    <Card className="min-w-0 gap-2 py-4">
      <CardHeader className="px-4">
        <CardTitle>Without vs with WattWise</CardTitle>
        <CardDescription>Total kW, last 3 sim hours + 2 h forecast · simulated</CardDescription>
      </CardHeader>
      <CardContent className="h-64 px-2">
        <LanesLines />
      </CardContent>
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
            y={withMeter.target_kw}
            stroke="var(--cap-line)"
            strokeDasharray="6 4"
            label={{ value: `Target ${fmtKw(withMeter.target_kw)}`, position: "insideTopLeft", fontSize: 11, fill: "var(--cap-line)" }}
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
