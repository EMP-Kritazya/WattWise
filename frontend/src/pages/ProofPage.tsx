import { useMemo, useState } from "react";
import { CheckCircle2, CircleAlert, FlaskConical, LoaderCircle, ShieldAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { backtestMonthOf, useBacktestRows, useDashboardStore as useSim } from "@/data";
import { fmtUsd } from "@/lib/format";
import { transport } from "@/transport";
import type { BacktestResult } from "@/types";
import { SavedChart } from "./proof/SavedChart";
import { MONTH_NAMES, tariffLabel } from "./proof/proofChart";

/** The replay calendar's 12 months (dataset 2018 + day_offset 2919 days, DATA_AND_PROOF.md). */
const YEAR_MONTHS = Array.from({ length: 12 }, (_, i) => `2026-${String(i + 1).padStart(2, "0")}`);

/**
 * Proof (UI.md section 4, Mode A): a year of restaurant data replayed through the engine. The line is each day's
 * `saved_month_to_date_usd`; each month ends with a mark at its `saved_usd`. Rows come from `useBacktestRows()`
 * (SpacetimeDB `backtest_point` / `backtest_month`, /ws fallback, or the fixture tables in mock mode); values are drawn as
 * published, never subtracted here.
 */
export function ProofPage() {
  const { runId, points, months } = useBacktestRows();
  const progress = useSim((s) => (runId ? s.backtestProgress[runId] : undefined));
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const results = useMemo<BacktestResult[]>(() => months.map(backtestMonthOf), [months]);
  const first = points[0] ?? months[0];
  const dataset = first?.dataset;
  const simulated = !!dataset && !dataset.startsWith("DOE-calibrated");

  const run = async () => {
    setStarting(true);
    setError(null);
    try {
      await transport.runBacktest({ months: YEAR_MONTHS, assumptions_id: "base" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Backtest failed to start");
    } finally {
      setStarting(false);
    }
  };

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 p-5 xl:p-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <FlaskConical className="size-5 text-primary" />
            <h1 className="text-2xl font-semibold tracking-tight">Proof</h1>
          </div>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            A year of restaurant load replayed through the WattWise engine on one tariff: without control, a fixed timer, and
            with WattWise, through the same loop.
          </p>
          <div className="mt-2 flex flex-wrap gap-2 text-xs">
            <Badge variant="outline">{dataset ?? "no run yet"}</Badge>
            <Badge variant="outline">{tariffLabel(first?.tariff_id)}</Badge>
            {first && <Badge variant="outline">assumptions {first.assumptions_id}</Badge>}
            {simulated && <Badge variant="outline" className="border-amber-500/35 text-amber-300">fixture data, not savings</Badge>}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={run} disabled={starting}>
            {starting && <LoaderCircle className="mr-2 size-4 animate-spin" />}
            Replay the year
          </Button>
        </div>
      </div>

      {/* No savings number is final until backtest-auditor returns CLEARED (CLAUDE.md "Honesty"). */}
      <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-200">
        <ShieldAlert className="size-4 shrink-0" />
        Engine output under review: not yet cleared by the backtest audit. Calibrated model data, not a measured bill.
      </div>

      {error && (
        <Card className="border-destructive/40">
          <CardContent className="flex items-center gap-2 pt-6 text-sm text-destructive">
            <CircleAlert className="size-4" /> {error}
          </CardContent>
        </Card>
      )}

      <Card className="gap-2 py-4">
        <CardHeader className="px-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <CardTitle>Dollars saved, month by month</CardTitle>
              <CardDescription>
                Line: saved this month so far (without − with, engine-computed each day). Mark: the month's total at its end.
              </CardDescription>
            </div>
            {progress && progress.pct < 100 && (
              <Badge variant="outline" className="tabular-nums">
                replaying {progress.month} · {progress.pct}%
              </Badge>
            )}
          </div>
        </CardHeader>
        <CardContent className="h-80 px-2">
          {points.length || months.length ? (
            <SavedChart points={points} months={months} />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
              No backtest rows yet. Start a replay to watch the year play.
            </div>
          )}
        </CardContent>
      </Card>

      {results.length > 0 && <MonthTable results={results} firstMonth={results[0].month} />}
    </div>
  );
}

function MonthTable({ results, firstMonth }: { results: BacktestResult[]; firstMonth: string }) {
  return (
    <Card className="gap-2 py-4">
      <CardHeader className="px-4">
        <CardTitle>Monthly bills</CardTitle>
        <CardDescription>Bills on the tariff for each policy; saved = engine-computed difference.</CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto px-4">
        <table className="w-full text-sm tabular-nums">
          <thead className="text-xs text-muted-foreground">
            <tr className="text-left">
              <th className="py-1.5 pr-3 font-medium">Month</th>
              <th className="py-1.5 pr-3 text-right font-medium">Without</th>
              <th className="py-1.5 pr-3 text-right font-medium">Timer</th>
              <th className="py-1.5 pr-3 text-right font-medium">With</th>
              <th className="py-1.5 pr-3 text-right font-medium">Saved</th>
              <th className="py-1.5 pr-3 text-right font-medium">vs timer</th>
              <th className="py-1.5 font-medium">Checks</th>
            </tr>
          </thead>
          <tbody>
            {results.map((r) => (
              <tr key={r.month} className="border-t border-border/60">
                <td className="py-1.5 pr-3">
                  {MONTH_NAMES[Number(r.month.slice(5, 7)) - 1]} {r.month.slice(0, 4)}
                  {r.partial && (
                    <span className="ml-1.5 text-xs text-muted-foreground">
                      {r.month === firstMonth ? "partial (warm-up)" : "partial"}
                    </span>
                  )}
                </td>
                <td className="py-1.5 pr-3 text-right">{fmtUsd(r.policies.without.total_usd)}</td>
                <td className="py-1.5 pr-3 text-right">{fmtUsd(r.policies.timer.total_usd)}</td>
                <td className="py-1.5 pr-3 text-right">{fmtUsd(r.policies.with.total_usd)}</td>
                <td className="py-1.5 pr-3 text-right font-medium">{fmtUsd(r.saved_usd)}</td>
                <td className="py-1.5 pr-3 text-right">{fmtUsd(r.saved_vs_timer_usd)}</td>
                <td className="py-1.5">
                  <Checks result={r} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function Checks({ result }: { result: BacktestResult }) {
  const ok = result.checks.baseline_matches_raw && result.checks.energy_conserved && result.checks.rule_violations === 0;
  return (
    <Badge variant="outline" className={ok ? "border-emerald-500/35 text-emerald-400" : "border-amber-500/35 text-amber-300"}>
      {ok && <CheckCircle2 className="mr-1 size-3" />}
      {ok ? "passed" : `${result.checks.rule_violations} violations`}
    </Badge>
  );
}
