import { useState } from "react";
import { CheckCircle2, CircleAlert, FlaskConical, LoaderCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { fmtUsd } from "@/lib/format";
import { transport } from "@/transport";
import type { BacktestResult, Bill } from "@/types";

type State =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; results: BacktestResult[] }
  | { kind: "error"; message: string };

/** Proof renders only the BacktestResult contract. No browser-derived savings or invented proof extensions. */
export function ProofPage() {
  const [state, setState] = useState<State>({ kind: "idle" });

  const run = async () => {
    setState({ kind: "loading" });
    try {
      const { run_id } = await transport.runBacktest({ months: ["2026-07"], assumptions_id: "base" });
      setState({ kind: "ready", results: await transport.getBacktest(run_id) });
    } catch (error) {
      setState({ kind: "error", message: error instanceof Error ? error.message : "Backtest failed" });
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
            Recorded restaurant data replayed under the same tariff and assumptions for each policy.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline">fake fixture data</Badge>
          <Button onClick={run} disabled={state.kind === "loading"}>
            {state.kind === "loading" && <LoaderCircle className="mr-2 size-4 animate-spin" />}
            Run fixture backtest
          </Button>
        </div>
      </div>

      {state.kind === "idle" && (
        <Card>
          <CardHeader>
            <CardTitle>Ready to replay</CardTitle>
            <CardDescription>The current contract exposes policy bills and validation checks for each completed month.</CardDescription>
          </CardHeader>
        </Card>
      )}

      {state.kind === "error" && (
        <Card className="border-destructive/40">
          <CardContent className="flex items-center gap-2 pt-6 text-sm text-destructive">
            <CircleAlert className="size-4" /> {state.message}
          </CardContent>
        </Card>
      )}

      {state.kind === "ready" && state.results.map((result) => <MonthResult key={`${result.month}:${result.assumptions_id}`} result={result} />)}
    </div>
  );
}

function MonthResult({ result }: { result: BacktestResult }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle>{result.month}</CardTitle>
            <CardDescription>{result.dataset} · assumptions {result.assumptions_id}</CardDescription>
          </div>
          <Checks result={result} />
        </div>
      </CardHeader>
      <CardContent className="grid gap-3 md:grid-cols-3">
        <BillCard title="Without WattWise" bill={result.policies.without} />
        <BillCard title="Timer policy" bill={result.policies.timer} />
        <BillCard title="With WattWise" bill={result.policies.with} accent />
      </CardContent>
    </Card>
  );
}

function BillCard({ title, bill, accent = false }: { title: string; bill: Bill; accent?: boolean }) {
  return (
    <div className={accent ? "rounded-xl border border-primary/35 bg-primary/5 p-4" : "rounded-xl border bg-muted/20 p-4"}>
      <div className="text-sm font-medium">{title}</div>
      <div className="mt-2 text-2xl font-semibold tabular-nums">{fmtUsd(bill.total_usd)}</div>
      <dl className="mt-3 space-y-1.5 text-xs text-muted-foreground">
        <Row label="Energy" value={`${bill.energy_kwh.toLocaleString()} kWh`} />
        <Row label="Energy cost" value={fmtUsd(bill.energy_cost_usd)} />
        {bill.demand_charges.map((charge) => (
          <Row key={charge.name} label={`${charge.name} · ${charge.peak_kw.toFixed(1)} kW`} value={fmtUsd(charge.cost_usd)} />
        ))}
      </dl>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return <div className="flex justify-between gap-3"><dt>{label}</dt><dd className="tabular-nums text-foreground">{value}</dd></div>;
}

function Checks({ result }: { result: BacktestResult }) {
  const ok = result.checks.baseline_matches_raw && result.checks.energy_conserved && result.checks.rule_violations === 0;
  return (
    <Badge variant="outline" className={ok ? "border-emerald-500/35 text-emerald-400" : "border-amber-500/35 text-amber-300"}>
      {ok && <CheckCircle2 className="mr-1 size-3" />}
      {ok ? "Checks passed" : `${result.checks.rule_violations} rule violations`}
    </Badge>
  );
}
