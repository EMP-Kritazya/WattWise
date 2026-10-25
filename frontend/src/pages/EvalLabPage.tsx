import { useMemo, useState } from "react";
import { CheckCircle2, CircleAlert, LoaderCircle, Microscope, TriangleAlert, XCircle } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { NoData } from "@/components/NoData";
import { Badge } from "@/components/ui/badge";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useEvalArtifact } from "@/data";
import { fmtKw, fmtSimTime, fmtUsd } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { EvalArtifact, EvalResult, EvalStrategy } from "@/types";

const INK = "#22223B";
const FAIL = "#EF476F";
const GRID = "rgb(34 34 59 / 14%)";
const AXIS_TICK = { fontSize: 11, fill: "var(--muted-foreground)" };
const TOOLTIP = {
  contentStyle: { background: "var(--popover)", border: "2px solid var(--border)", borderRadius: 14, fontSize: 12, boxShadow: "0 3px 0 #22223B" },
  labelStyle: { color: "var(--muted-foreground)" },
};
const BASELINE_ID = "unoptimized";
const cardClass = "min-w-0 rounded-[22px] border-2 border-[#22223B] bg-white p-4 text-[#22223B] shadow-[0_5px_0_#22223B]";
const headingClass = "font-['Fredoka',sans-serif] text-base font-bold tracking-tight";

/** One colour per strategy kind; the baseline and WattWise keep the lane colours (UI.md visual language). */
function strategyColor(strategy: EvalStrategy): string {
  if (strategy.strategy_id === BASELINE_ID) return "var(--lane-without)";
  if (strategy.kind === "wattwise") return "var(--lane-with)";
  if (strategy.kind === "oracle") return "#9A91A4";
  return { conservative_hvac: "#A9D6F5", balanced_hvac: "#FFB703", aggressive_hvac: "#C3A3E8" }[strategy.strategy_id] ?? "#FFD6A5";
}

/** Evaluation Lab (docs/Claude_EVAL.md §11): renders one precomputed eval artifact; the browser computes nothing. */
export function EvalLabPage() {
  const state = useEvalArtifact();

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 p-4 sm:p-5 xl:p-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Microscope className="size-5 text-primary" />
            <h1 className="font-['Fredoka',sans-serif] text-3xl font-bold tracking-tight">Evaluation Lab</h1>
          </div>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            The same scenario, the same customers and weather, run under each strategy. Any broken hard rule fails the strategy, however
            much it saves.
          </p>
        </div>
        {state.kind === "ready" && <SourceBadge artifact={state.artifact} />}
      </div>

      {state.kind === "loading" && (
        <div className={cn(cardClass, "flex items-center gap-2 text-sm")}>
          <LoaderCircle className="size-4 animate-spin" /> Loading eval results…
        </div>
      )}
      {state.kind === "error" && (
        <div className={cn(cardClass, "flex items-center gap-2 text-sm text-destructive")}>
          <CircleAlert className="size-4" /> {state.message}
        </div>
      )}
      {state.kind === "empty" && (
        <NoData title="No evaluation results yet">
          No eval run has published results. The Lab shows each strategy's bills, peaks and rule checks once the eval runner
          (docs/Claude_EVAL.md) produces a real artifact; nothing is shown in the meantime.
        </NoData>
      )}
      {state.kind === "ready" && <Lab artifact={state.artifact} />}
    </div>
  );
}

function SourceBadge({ artifact }: { artifact: EvalArtifact }) {
  return artifact.source === "illustrative_stub" ? (
    <Badge variant="outline" className="border-[#22223B] bg-[#FFF0BA] text-[#704A00]">
      illustrative placeholder
    </Badge>
  ) : (
    <Badge variant="outline" className="border-[#22223B] bg-[#DFF6F3] text-[#167D74]">
      simulated · {artifact.run_id}
    </Badge>
  );
}

function Lab({ artifact }: { artifact: EvalArtifact }) {
  const [scenarioId, setScenarioId] = useState(artifact.scenarios[0]?.scenario_id ?? "");
  const [strategyId, setStrategyId] = useState(
    artifact.strategies.find((s) => s.kind === "wattwise")?.strategy_id ?? artifact.strategies[0]?.strategy_id ?? "",
  );
  const scenario = artifact.scenarios.find((s) => s.scenario_id === scenarioId);
  const results = useMemo(() => artifact.results.filter((r) => r.scenario_id === scenarioId), [artifact, scenarioId]);
  const strategies = artifact.strategies;
  const byStrategy = useMemo(() => new Map(results.map((r) => [r.strategy_id, r])), [results]);
  const selected = byStrategy.get(strategyId);
  const selectedStrategy = strategies.find((s) => s.strategy_id === strategyId);

  return (
    <>
      {artifact.source === "illustrative_stub" && (
        <div className="flex items-start gap-3 rounded-[18px] border-2 border-[#22223B] bg-[#FFF0BA] px-4 py-3 text-sm font-semibold text-[#704A00]">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" />
          <p>
            Illustrative placeholder, not evaluation output. No eval has been run yet; these values only show what the Lab will display.
          </p>
        </div>
      )}

      <section className={cn(cardClass, "flex flex-col gap-4")} aria-label="Scenario and strategy">
        <div className="flex flex-col gap-2">
          <h2 className={headingClass}>1 · Scenario</h2>
          <ToggleGroup
            type="single"
            variant="outline"
            value={scenarioId}
            onValueChange={(v) => v && setScenarioId(v)}
            className="flex w-full flex-wrap justify-start gap-2"
          >
            {artifact.scenarios.map((s) => (
              <ToggleGroupItem key={s.scenario_id} value={s.scenario_id} className="h-auto gap-2 rounded-xl px-3 py-1.5">
                <span className="font-extrabold">{s.name}</span>
                {s.split === "held_out" && <span className="text-[10px] uppercase tracking-wide opacity-70">held out</span>}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          {scenario && (
            <p className="text-sm text-muted-foreground">
              {scenario.summary} Outdoor max {scenario.outdoor_max_c.toFixed(0)} °C · {scenario.traffic_label} · cap{" "}
              {fmtKw(scenario.peak_cap_kw)}.
            </p>
          )}
        </div>
        <div className="flex flex-col gap-2">
          <h2 className={headingClass}>2 · Strategy</h2>
          <div className="flex flex-wrap gap-2">
            {strategies.map((s) => {
              const r = byStrategy.get(s.strategy_id);
              const active = s.strategy_id === strategyId;
              return (
                <button
                  key={s.strategy_id}
                  type="button"
                  onClick={() => setStrategyId(s.strategy_id)}
                  aria-pressed={active}
                  className={cn(
                    "flex items-center gap-2 rounded-xl border-2 border-[#22223B] px-3 py-1.5 text-sm font-extrabold transition-all",
                    active ? "bg-[#FFE7D1] shadow-[0_3px_0_#22223B]" : "bg-white hover:bg-[#FFF6E9]",
                  )}
                >
                  <span className="size-3 rounded-full border-2 border-[#22223B]" style={{ background: strategyColor(s) }} />
                  {s.name}
                  {r?.verdict === "fail" && <XCircle className="size-4 text-[#EF476F]" aria-label="failed" />}
                  {!s.deployable && <span className="text-[10px] uppercase opacity-70">diagnostic</span>}
                </button>
              );
            })}
          </div>
          {selectedStrategy && <p className="text-sm text-muted-foreground">{selectedStrategy.summary}</p>}
        </div>
      </section>

      {selected && selectedStrategy && <Headline result={selected} strategy={selectedStrategy} />}

      <div className="grid gap-5 lg:grid-cols-2">
        <CostComfortScatter results={results} strategies={strategies} selectedId={strategyId} onSelect={setStrategyId} />
        <DemandChart
          baseline={byStrategy.get(BASELINE_ID)}
          selected={selected}
          strategy={selectedStrategy}
          capKw={scenario?.peak_cap_kw}
        />
      </div>

      <Scorecard artifact={artifact} results={results} strategies={strategies} selectedId={strategyId} />

      <div className="grid gap-5 lg:grid-cols-2">
        <CostBreakdown results={results} strategies={strategies} />
        <div className="flex min-w-0 flex-col gap-5">
          <TraceCard result={selected} strategy={selectedStrategy} />
          <Provenance artifact={artifact} />
        </div>
      </div>
    </>
  );
}

function Headline({ result, strategy }: { result: EvalResult; strategy: EvalStrategy }) {
  const tiles = [
    { label: "Projected bill", value: fmtUsd(result.bill.total_usd) },
    { label: "Saved vs no control", value: fmtUsd(result.savings_usd) },
    { label: "15-min peak", value: fmtKw(result.peak_demand_kw) },
    { label: "Peak avoided", value: fmtKw(result.peak_avoided_kw) },
    { label: "Hottest indoor", value: `${result.comfort.max_indoor_temp_c.toFixed(1)} °C` },
  ];
  const pass = result.verdict === "pass";
  return (
    <section className={cn(cardClass, "flex flex-col gap-3")} aria-live="polite" aria-label={`${strategy.name} result`}>
      <div className="flex flex-wrap items-center gap-2">
        <h2 className={headingClass}>{strategy.name}</h2>
        <VerdictChip pass={pass} />
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
        {tiles.map((t) => (
          <div key={t.label} className="rounded-2xl bg-[#FFF6E9] px-3 py-2">
            <div className="text-[10px] font-extrabold uppercase tracking-wide opacity-70">{t.label}</div>
            <div className="font-['Fredoka',sans-serif] text-xl font-bold tabular-nums">{t.value}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function VerdictChip({ pass }: { pass: boolean }) {
  return pass ? (
    <span className="inline-flex items-center gap-1 rounded-full border-2 border-[#22223B] bg-[#DFF6F3] px-2 py-0.5 text-xs font-extrabold text-[#167D74]">
      <CheckCircle2 className="size-3" /> PASS
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 rounded-full border-2 border-[#22223B] bg-[#FFE0E7] px-2 py-0.5 text-xs font-extrabold text-[#B3123C]">
      <XCircle className="size-3" /> FAIL
    </span>
  );
}

interface ScatterPoint {
  strategy_id: string;
  name: string;
  cost: number;
  comfort: number;
  fail: boolean;
  color: string;
  selected: boolean;
}

function ScatterDot({ cx, cy, payload }: { cx?: number; cy?: number; payload?: ScatterPoint }) {
  if (cx == null || cy == null || !payload) return null;
  const r = payload.selected ? 10 : 7;
  return (
    <g>
      {payload.selected && <circle cx={cx} cy={cy} r={r + 5} fill="none" stroke={INK} strokeWidth={2} strokeDasharray="3 3" />}
      {payload.fail ? (
        <g stroke={FAIL} strokeWidth={4} strokeLinecap="round">
          <line x1={cx - r} y1={cy - r} x2={cx + r} y2={cy + r} />
          <line x1={cx - r} y1={cy + r} x2={cx + r} y2={cy - r} />
        </g>
      ) : (
        <circle cx={cx} cy={cy} r={r} fill={payload.color} stroke={INK} strokeWidth={2} />
      )}
    </g>
  );
}

function CostComfortScatter({
  results,
  strategies,
  selectedId,
  onSelect,
}: {
  results: EvalResult[];
  strategies: EvalStrategy[];
  selectedId: string;
  onSelect: (id: string) => void;
}) {
  const points: ScatterPoint[] = strategies.flatMap((s) => {
    const r = results.find((x) => x.strategy_id === s.strategy_id);
    return r
      ? [
          {
            strategy_id: s.strategy_id,
            name: s.name,
            cost: r.bill.total_usd,
            comfort: r.comfort.degree_minutes_above,
            fail: r.verdict === "fail",
            color: strategyColor(s),
            selected: s.strategy_id === selectedId,
          },
        ]
      : [];
  });

  return (
    <section className={cardClass} aria-label="Cost versus comfort">
      <h2 className={headingClass}>Cost vs comfort</h2>
      <p className="text-xs text-muted-foreground">Lower and further left is better. ✕ = broke a hard rule. Tap a point to inspect it.</p>
      <div className="mt-2 h-64">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 12, right: 16, bottom: 18, left: 4 }}>
            <CartesianGrid stroke={GRID} />
            <XAxis
              type="number"
              dataKey="cost"
              name="Projected bill"
              domain={["auto", "auto"]}
              tick={AXIS_TICK}
              stroke={GRID}
              tickFormatter={(v: number) => `$${v.toFixed(0)}`}
              label={{ value: "Projected bill ($)", position: "insideBottom", offset: -10, fontSize: 11, fill: "var(--muted-foreground)" }}
            />
            <YAxis
              type="number"
              dataKey="comfort"
              name="Degree-minutes above comfort"
              tick={AXIS_TICK}
              stroke={GRID}
              width={40}
              label={{ value: "°C·min too warm", angle: -90, position: "insideLeft", fontSize: 11, fill: "var(--muted-foreground)" }}
            />
            <ZAxis range={[120, 120]} />
            <Tooltip
              {...TOOLTIP}
              cursor={{ strokeDasharray: "3 3" }}
              content={({ payload }) => {
                const p = payload?.[0]?.payload as ScatterPoint | undefined;
                if (!p) return null;
                return (
                  <div style={TOOLTIP.contentStyle} className="px-3 py-2">
                    <div className="font-extrabold">{p.name}{p.fail ? " · FAIL" : ""}</div>
                    <div>{fmtUsd(p.cost)} · {p.comfort.toFixed(1)} °C·min</div>
                  </div>
                );
              }}
            />
            <Scatter
              data={points}
              shape={(props: unknown) => <ScatterDot {...(props as { cx?: number; cy?: number; payload?: ScatterPoint })} />}
              onClick={(p: unknown) => {
                const id = (p as { payload?: ScatterPoint })?.payload?.strategy_id;
                if (id) onSelect(id);
              }}
              isAnimationActive={false}
              className="cursor-pointer"
            />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

function DemandChart({
  baseline,
  selected,
  strategy,
  capKw,
}: {
  baseline: EvalResult | undefined;
  selected: EvalResult | undefined;
  strategy: EvalStrategy | undefined;
  capKw: number | undefined;
}) {
  const data = useMemo(() => {
    const rows = new Map<number, { t: number; baseline?: number; selected?: number }>();
    const row = (t: number) => rows.get(t) ?? rows.set(t, { t }).get(t)!;
    for (const b of baseline?.demand_blocks ?? []) row(Date.parse(b.block_start_ts)).baseline = b.demand_kw;
    if (selected && selected.strategy_id !== baseline?.strategy_id)
      for (const b of selected.demand_blocks) row(Date.parse(b.block_start_ts)).selected = b.demand_kw;
    return [...rows.values()].sort((a, b) => a.t - b.t);
  }, [baseline, selected]);

  return (
    <section className={cardClass} aria-label="15-minute demand">
      <h2 className={headingClass}>15-minute demand</h2>
      <p className="text-xs text-muted-foreground">Average kW per 15-minute block, no control vs {strategy?.name ?? "selected"}
        {capKw != null && <> · dashed line = cap {fmtKw(capKw)}</>} · simulated
      </p>
      <div className="mt-2 h-64">
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
            {capKw != null && (
              <ReferenceLine y={capKw} stroke="var(--cap-line)" strokeDasharray="6 4" />
            )}
            <Line
              name="No control (simulated)"
              dataKey="baseline"
              type="stepAfter"
              stroke="var(--lane-without)"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
            {strategy && strategy.strategy_id !== BASELINE_ID && (
              <Line
                name={`${strategy.name} (simulated)`}
                dataKey="selected"
                type="stepAfter"
                stroke={strategy.kind === "wattwise" ? "var(--lane-with)" : INK}
                strokeWidth={2.5}
                dot={false}
                isAnimationActive={false}
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

function CostBreakdown({ results, strategies }: { results: EvalResult[]; strategies: EvalStrategy[] }) {
  const data = strategies.flatMap((s) => {
    const r = results.find((x) => x.strategy_id === s.strategy_id);
    return r ? [{ name: s.name, energy: r.bill.energy_usd, demand: r.bill.demand_usd, total: r.bill.total_usd }] : [];
  });

  return (
    <section className={cardClass} aria-label="Cost breakdown">
      <h2 className={headingClass}>Where the money goes</h2>
      <p className="text-xs text-muted-foreground">Energy charge vs demand charge per strategy · illustrative tariff</p>
      <div className="mt-2 h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ top: 4, right: 16, bottom: 0, left: 8 }}>
            <CartesianGrid stroke={GRID} horizontal={false} />
            <XAxis type="number" tick={AXIS_TICK} stroke={GRID} tickFormatter={(v: number) => `$${v.toFixed(0)}`} />
            <YAxis type="category" dataKey="name" tick={AXIS_TICK} stroke={GRID} width={110} />
            <Tooltip {...TOOLTIP} formatter={(v) => fmtUsd(Number(v))} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Bar dataKey="energy" name="Energy charge" stackId="bill" fill="#A9D6F5" stroke={INK} isAnimationActive={false} />
            <Bar dataKey="demand" name="Demand charge" stackId="bill" fill="#FFB4A2" stroke={INK} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

function Scorecard({
  artifact,
  results,
  strategies,
  selectedId,
}: {
  artifact: EvalArtifact;
  results: EvalResult[];
  strategies: EvalStrategy[];
  selectedId: string;
}) {
  return (
    <section className={cardClass} aria-label="Hard-rule scorecard">
      <h2 className={headingClass}>Hard rules</h2>
      <p className="text-xs text-muted-foreground">Violations counted by the eval runner. One violation fails the strategy.</p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[560px] border-separate border-spacing-y-1 text-xs">
          <thead>
            <tr className="text-left text-muted-foreground">
              <th className="pr-2 font-extrabold">Rule</th>
              {strategies.map((s) => (
                <th key={s.strategy_id} className={cn("px-1 text-center font-extrabold", s.strategy_id === selectedId && "text-[#22223B]")}>
                  {s.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {artifact.hard_constraints.map((c) => (
              <tr key={c.constraint_id}>
                <td className="pr-2 font-semibold">{c.label}</td>
                {strategies.map((s) => {
                  const count = results.find((r) => r.strategy_id === s.strategy_id)?.violations.find((v) => v.constraint_id === c.constraint_id)?.count;
                  return (
                    <td key={s.strategy_id} className={cn("text-center", s.strategy_id === selectedId && "bg-[#FFF6E9]")}>
                      {count == null ? "–" : count === 0 ? (
                        <CheckCircle2 className="mx-auto size-4 text-[#168F84]" aria-label="no violations" />
                      ) : (
                        <span className="font-extrabold text-[#B3123C]">✕ {count}</span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
            <tr>
              <td className="pr-2 pt-2 font-extrabold">Verdict</td>
              {strategies.map((s) => {
                const r = results.find((x) => x.strategy_id === s.strategy_id);
                return (
                  <td key={s.strategy_id} className="pt-2 text-center">
                    {r ? <VerdictChip pass={r.verdict === "pass"} /> : "–"}
                  </td>
                );
              })}
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}

function TraceCard({ result, strategy }: { result: EvalResult | undefined; strategy: EvalStrategy | undefined }) {
  const trace = result?.trace;
  return (
    <section className={cardClass} aria-label="One decision from the run">
      <h2 className={headingClass}>One decision from this run</h2>
      {trace ? (
        <div className="mt-2 flex flex-col gap-2 text-sm">
          <div className="text-xs text-muted-foreground">{fmtSimTime(trace.ts)} · {strategy?.name} · simulated</div>
          <div className="font-['Fredoka',sans-serif] text-lg font-bold">
            {trace.device_name}: {trace.action}
          </div>
          <p>{trace.reason}</p>
          <div className="rounded-2xl bg-[#FFF6E9] px-3 py-2 font-semibold tabular-nums">
            15-min peak {fmtKw(trace.peak_before_kw)} → {fmtKw(trace.peak_after_kw)}
          </div>
          <div className="text-xs text-muted-foreground">
            {result?.operations.commands} commands · {result?.operations.escalations} escalations · {result?.operations.unmet_kwh.toFixed(1)} kWh unmet
          </div>
        </div>
      ) : (
        <p className="mt-2 text-sm text-muted-foreground">No control sends no commands, so there is no decision to show.</p>
      )}
    </section>
  );
}

function Provenance({ artifact }: { artifact: EvalArtifact }) {
  const p = artifact.provenance;
  const rows = [
    ["Run", artifact.run_id],
    ["Source", artifact.source === "illustrative_stub" ? "illustrative placeholder" : "simulated"],
    ["Engine", p.engine_version],
    ["Evaluation plant", p.plant],
    ["Tariff", `${p.tariff_id} (${p.tariff_label})`],
    ["Seeds", p.seeds.join(", ")],
  ];
  return (
    <section className={cardClass} aria-label="Provenance">
      <h2 className={headingClass}>Where these numbers come from</h2>
      <dl className="mt-2 space-y-1.5 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="flex justify-between gap-3">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="text-right font-semibold">{value}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-[11px] font-extrabold uppercase tracking-[0.14em] opacity-70">
        Simulated estimates · not measured restaurant savings
      </p>
    </section>
  );
}
