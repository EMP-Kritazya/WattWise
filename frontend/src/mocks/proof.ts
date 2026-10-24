import type { BacktestResult, Bill } from "@/types";

// Legacy hand-written mock retained until the fixture REST transport replaces it in A3.
export const DEMAND_USD_PER_KW = 20.5;
const ENERGY_USD_PER_KWH = 0.19;
const YEAR = 2025;
export const MOCK_MONTHS = Array.from({ length: 12 }, (_, i) => `${YEAR}-${String(i + 1).padStart(2, "0")}`);
const round2 = (n: number) => Math.round(n * 100) / 100;
const season = (i: number) => 1 + 0.25 * Math.sin((Math.PI * (i - 3)) / 6);

function mockBill(period: string, energyKwh: number, peakKw: number): Bill {
  const energyCost = round2(energyKwh * ENERGY_USD_PER_KWH);
  const demandCost = round2(peakKw * DEMAND_USD_PER_KW);
  return {
    period,
    energy_kwh: round2(energyKwh),
    energy_cost_usd: energyCost,
    demand_charges: [{ name: "max_demand", peak_kw: round2(peakKw), cost_usd: demandCost }],
    total_usd: round2(energyCost + demandCost),
    tariff_id: "mock-tariff",
  };
}

export function mockBacktestMonth(month: string, i: number): BacktestResult {
  const energyKwh = 21_000 * season(i);
  const peakWithout = 44 * season(i);
  return {
    dataset: "MOCK DATA, not a real dataset",
    month,
    policies: {
      without: mockBill(month, energyKwh, peakWithout),
      timer: mockBill(month, energyKwh, peakWithout - 2.5),
      with: mockBill(month, energyKwh, peakWithout - 6.5),
    },
    checks: { baseline_matches_raw: true, energy_conserved: true, rule_violations: 0 },
    assumptions_id: "base",
  };
}
