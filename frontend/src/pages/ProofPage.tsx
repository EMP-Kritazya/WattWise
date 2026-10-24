import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, LoaderCircle, RefreshCw, ShieldAlert, XCircle } from "lucide-react";
import { CartesianGrid, Line, LineChart, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ReplayMonth } from "@/components/proof/ReplayMonth";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useLive as useSim } from "@/data";
import { useAction } from "@/hooks/useAction";
import { fmtKw, fmtSimTime, fmtUsd } from "@/lib/format";
import { LANE_COLOR } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { transport } from "@/transport";
import type { BacktestResult, Bill, ProofExtras } from "@/types";

// The Proof screen (UI.md §4, DATA_AND_PROOF.md): twelve months billed three ways, the busiest day, sensitivity and
// Replay month. Every number comes from the engine (BacktestResult + the PROPOSED ProofExtras); nothing is computed here.

const monthFmt = new Intl.DateTimeFormat("en-US", { timeZone: "UTC", month: "short", year: "numeric" });
const dayFmt = new Intl.DateTimeFormat("en-US", { timeZone: "America/Los_Angeles", weekday: "long", month: "long", day: "numeric", year: "numeric" });
const kwhFmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const fmtMonth = (m: string) => monthFmt.format(new Date(`${m}-01T00:00:00Z`));
const POLICIES = [
  { key: "without", label: "Without", color: LANE_COLOR.without },
  { key: "timer", label: "Timer", color: "var(--muted-foreground)" },
  { key: "with", label: "With WattWise", color: LANE_COLOR.with },
] as const;
const AXIS_TICK = { fontSize: 11, fill: "var(--muted-foreground)" };
const TOOLTIP = {
  contentStyle: { background: "var(--popover)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 },
  labelStyle: { color: "var(--muted-foreground)" },
};

interface ProofData {
  results: BacktestResult[];
  extras: ProofExtras;
}
// The last finished run, kept while the app is open so the screen doesn't re-run on every visit.
let lastRun: ProofData | null = null;

function useBacktest() {
  const [data, setData] = useState<ProofData | null>(lastRun);
  const [runId, setRunId] = useState<string | null>(null);
  const progress = useSim((s) => (runId ? s.backtestProgress[runId] : undefined));
  const { run, busy, error } = useAction();

  const start = useCallback(
    () =>
      run(async () => {
        lastRun = null;
        setData(null);
        const { run_id } = await transport.runBacktest({ months: 12, assumptions_id: "base" });
        setRunId(run_id);
      }),
    [run],
  );

  useEffect(() => {
    if (!lastRun) start();
  }, [start]);

  const finished = progress?.pct === 100;
  useEffect(() => {
    if (!runId || !finished) return;
    run(async () => {
      const [results, extras] = await Promise.all([transport.getBacktest(runId), transport.getProofExtras(runId)]);
      lastRun = { results, extras };
      setData(lastRun);
    });
  }, [runId, finished, run]);

  return { data, progress, running: !data && (busy || !!runId), error, start };
}

export function ProofPage() {
  const { data, progress, running, error, start } = useBacktest();
  const extras = data?.extras;
  const cleared = extras?.audit === "cleared";
  const replaySaved = extras?.months.find((m) => m.month === extras.replay.month);

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4 p-4 xl:p-6">
      <header className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="text-2xl font-semibold">Proof</h1>
          <p className="text-muted-foreground">
            Twelve months billed three ways through the same loop and the same tariff. No peeking: the engine sees one 15-minute row at a
            time, and Claude is never in the scored run.
          </p>
          {data && (
            <div className="mt-2 flex flex-wrap gap-2">
              <Badge variant="outline">{data.results[0]?.dataset}</Badge>
              {extras && <Badge variant="outline">Tariff: {extras.tariff.name}</Badge>}
              <Badge variant="outline">Assumptions: {data.results[0]?.assumptions_id}</Badge>
              {extras && <AuditBadge audit={extras.audit} />}
            </div>
          )}
        </div>
        <Button variant="outline" size="sm" disabled={running} onClick={start}>
          {running ? <LoaderCircle className="animate-spin" /> : <RefreshCw />}
          {running ? (progress ? `Running… ${fmtMonth(progress.month)} · ${progress.pct}%` : "Starting…") : "Re-run backtest"}
        </Button>
      </header>
      {error && <p className="text-sm text-destructive">{error}</p>}

      {running && <RunningCard pct={progress?.pct ?? 0} />}
      {data && extras && !cleared && (
        <Card className="border-dashed py-6 text-center text-sm text-muted-foreground">
          The numbers stay hidden until the backtest auditor clears this run ({extras.audit}).
        </Card>
      )}

      {data && extras && cleared && (
        <>
          <Totals totals={extras.totals} />
          <ReplayMonth replay={extras.replay} savedVsWithout={replaySaved?.saved_vs_without_usd} savedVsTimer={replaySaved?.saved_vs_timer_usd} />
          <MonthTable results={data.results} extras={extras} />
          <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
            <BusiestDay day={extras.busiest_day} />
            <Sensitivity rows={extras.sensitivity} />
          </div>
        </>
      )}
    </div>
  );
}

function AuditBadge({ audit }: { audit: ProofExtras["audit"] }) {
  if (audit === "cleared")
    return (
      <Badge variant="outline" className="border-lane-with/40 text-lane-with">
        <CheckCircle2 /> Auditor: cleared
      </Badge>
    );
  return (
    <Badge variant="outline" className="border-importance-deferrable/40 text-importance-deferrable">
      <ShieldAlert /> Auditor: {audit}
    </Badge>
  );
}

function RunningCard({ pct }: { pct: number }) {
  return (
    <Card className="gap-2 px-4 py-4">
      <div className="text-sm text-muted-foreground">Replaying twelve months through the same loop…</div>
      <div className="h-2 overflow-hidden rounded-full bg-secondary">
        <div className="h-full rounded-full bg-lane-with transition-[width] duration-300" style={{ width: `${pct}%` }} />
      </div>
    </Card>
  );
}

function Totals({ totals }: { totals: ProofExtras["totals"] }) {
  const tiles = [
    { label: "Without WattWise · 12 months", value: totals.without_usd, color: LANE_COLOR.without },
    { label: "Best timer schedule", value: totals.timer_usd, color: "var(--muted-foreground)" },
    { label: "With WattWise", value: totals.with_usd, color: LANE_COLOR.with },
    { label: "Saved vs doing nothing", value: totals.saved_vs_without_usd, color: LANE_COLOR.with, strong: true },
    { label: "Saved vs the timer", value: totals.saved_vs_timer_usd, color: LANE_COLOR.with, strong: true },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
      {tiles.map((t) => (
        <div key={t.label} className={cn("rounded-xl border bg-card px-4 py-3", t.strong && "border-lane-with/40 bg-lane-with/5")}>
          <div className="text-xs text-muted-foreground">{t.label}</div>
          <div className="mt-0.5 text-xl font-semibold tabular-nums" style={{ color: t.color }}>
            {fmtUsd(t.value)}
          </div>
        </div>
      ))}
    </div>
  );
}

function MonthTable({ results, extras }: { results: BacktestResult[]; extras: ProofExtras }) {
  const saved = new Map(extras.months.map((m) => [m.month, m]));
  return (
    <Card className="gap-2 py-4">
      <CardHeader className="px-4">
        <CardTitle>Twelve months, three ways</CardTitle>
        <CardDescription>Peak kW and bill for each policy. The highest 15-minute block of the month sets the demand charge.</CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto px-4">
        <table className="w-full min-w-[760px] text-sm">
          <thead>
            <tr className="border-b text-left text-xs text-muted-foreground">
              <th className="py-2 pr-3 font-medium">Month</th>
              {POLICIES.map((p) => (
                <th key={p.key} className="py-2 pr-3 font-medium" style={{ color: p.color }}>
                  {p.label}
                </th>
              ))}
              <th className="py-2 pr-3 text-right font-medium">Saved vs without</th>
              <th className="py-2 pr-3 text-right font-medium">Saved vs timer</th>
              <th className="py-2 text-center font-medium">Checks</th>
            </tr>
          </thead>
          <tbody>
            {results.map((r) => {
              const s = saved.get(r.month);
              return (
                <tr key={r.month} className="border-b last:border-0">
                  <td className="py-2 pr-3 align-top">
                    <div className="font-medium">{fmtMonth(r.month)}</div>
                    {s?.partial && <div className="text-[11px] text-importance-deferrable">partial (warm-up)</div>}
                  </td>
                  {POLICIES.map((p) => (
                    <BillCell key={p.key} bill={r.policies[p.key]} />
                  ))}
                  <td className="py-2 pr-3 text-right align-top font-medium text-lane-with tabular-nums">{fmtUsd(s?.saved_vs_without_usd)}</td>
                  <td className="py-2 pr-3 text-right align-top tabular-nums">{fmtUsd(s?.saved_vs_timer_usd)}</td>
                  <td className="py-2 text-center align-top">
                    <ChecksCell checks={r.checks} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function BillCell({ bill }: { bill: Bill }) {
  const peak = bill.demand_charges[0]?.peak_kw;
  return (
    <td className="py-2 pr-3 align-top tabular-nums">
      <div>{fmtUsd(bill.total_usd)}</div>
      <div className="text-xs text-muted-foreground">
        peak {fmtKw(peak)} · {kwhFmt.format(bill.energy_kwh)} kWh
      </div>
    </td>
  );
}

function ChecksCell({ checks }: { checks: BacktestResult["checks"] }) {
  const ok = checks.baseline_matches_raw && checks.energy_conserved && checks.rule_violations === 0;
  const detail = `Baseline matches raw data: ${checks.baseline_matches_raw ? "yes" : "no"} · Energy conserved: ${checks.energy_conserved ? "yes" : "no"} · Rule violations: ${checks.rule_violations}`;
  const Icon = ok ? CheckCircle2 : XCircle;
  return (
    <span title={detail} aria-label={detail} className="inline-flex">
      <Icon className={cn("size-4", ok ? "text-lane-with" : "text-destructive")} />
    </span>
  );
}

function BusiestDay({ day }: { day: ProofExtras["busiest_day"] }) {
  const data = day.series.map((p) => ({ t: Date.parse(p.ts), without: p.without_kw, with: p.with_kw }));
  return (
    <Card className="min-w-0 gap-2 py-4">
      <CardHeader className="px-4">
        <CardTitle>Busiest day of the year</CardTitle>
        <CardDescription>
          {dayFmt.format(new Date(day.date))}: without WattWise the peak hit {fmtKw(day.peak_without_kw)}; with it, {fmtKw(day.peak_with_kw)}.
        </CardDescription>
      </CardHeader>
      <CardContent className="h-64 px-2">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -8 }}>
            <CartesianGrid stroke="oklch(1 0 0 / 7%)" vertical={false} />
            <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} scale="time" tick={AXIS_TICK} tickFormatter={(t) => fmtSimTime(t)} minTickGap={40} />
            <YAxis tick={AXIS_TICK} unit=" kW" width={64} />
            <Tooltip {...TOOLTIP} labelFormatter={(t) => fmtSimTime(Number(t))} formatter={(v) => fmtKw(Number(v))} />
            <ReferenceLine y={day.peak_without_kw} stroke={LANE_COLOR.without} strokeDasharray="4 4" />
            <ReferenceLine y={day.peak_with_kw} stroke={LANE_COLOR.with} strokeDasharray="4 4" />
            <ReferenceDot x={Date.parse(day.peak_without_ts)} y={day.peak_without_kw} r={4} fill={LANE_COLOR.without} stroke="none" />
            <Line dataKey="without" name="Without" stroke={LANE_COLOR.without} dot={false} strokeWidth={1.6} isAnimationActive={false} />
            <Line dataKey="with" name="With WattWise" stroke={LANE_COLOR.with} dot={false} strokeWidth={2} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}

function Sensitivity({ rows }: { rows: ProofExtras["sensitivity"] }) {
  return (
    <Card className="min-w-0 gap-2 py-4">
      <CardHeader className="px-4">
        <CardTitle>What if we're wrong?</CardTitle>
        <CardDescription>The same twelve months under harsher assumptions and other real tariffs. The worst case is highlighted.</CardDescription>
      </CardHeader>
      <CardContent className="px-4">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-xs text-muted-foreground">
              <th className="py-2 pr-2 font-medium">Scenario</th>
              <th className="py-2 pr-2 text-right font-medium">Saved / year</th>
              <th className="py-2 text-right font-medium">of the bill</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className={cn("border-b last:border-0", r.worst && "bg-importance-deferrable/10")}>
                <td className="py-2 pr-2">
                  {r.label}
                  {r.kind === "tariff" && <span className="ml-1 text-[11px] text-muted-foreground">tariff</span>}
                  {r.worst && (
                    <Badge variant="outline" className="ml-2 border-importance-deferrable/40 text-importance-deferrable">
                      worst case
                    </Badge>
                  )}
                </td>
                <td className="py-2 pr-2 text-right tabular-nums">{fmtUsd(r.saved_usd_year)}</td>
                <td className="py-2 text-right text-muted-foreground tabular-nums">{r.saved_pct.toFixed(1)} %</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
