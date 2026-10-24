import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

// Phase 4 shell. Dataset and tariff labels must use the exact wording in docs/design/DATA_AND_PROOF.md.
const SECTIONS = [
  {
    title: "12-month bills",
    body: "Peak kW, energy kWh and bill $ for Without / Timer / With, plus savings columns. From GET /api/backtest/{run_id}.",
  },
  {
    title: "Busiest day",
    body: "Without vs with load with the month peak marked. Needs a daily load series that BacktestResult doesn't carry yet.",
  },
  {
    title: "Sensitivity",
    body: "low_flex, heavy_equipment, bad_forecast and two other tariffs, worst case highlighted.",
  },
  {
    title: "Replay month",
    body: "Animates a cached month in ~15 s with three bill counters ticking. Needs a replay series in the contract.",
  },
];

export function ProofPage() {
  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4 p-6">
      <div>
        <h1 className="text-2xl font-semibold">Proof</h1>
        <p className="text-muted-foreground">
          Twelve months of historical restaurant load, billed on a real tariff three ways. Built in Phase 4.
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {SECTIONS.map((s) => (
          <Card key={s.title} className="border-dashed">
            <CardHeader>
              <CardTitle>{s.title}</CardTitle>
              <CardDescription>{s.body}</CardDescription>
            </CardHeader>
          </Card>
        ))}
      </div>
    </div>
  );
}
