import type { BacktestResult, Bill, ProofExtras } from "@/types";
import { mulberry32 } from "./rng";

// MOCK backtest: twelve made-up months billed three ways, plus the PROPOSED ProofExtras the Proof screen needs.
// In the real system the engine computes all of this (DATA_AND_PROOF.md); here it only has to look plausible.

export const DEMAND_USD_PER_KW = 20.5;
const ENERGY_USD_PER_KWH = 0.19;
const YEAR = 2025;
const REPLAY_MONTH_INDEX = 6; // July: the busiest month
const STEP_MIN = 15;

export const MOCK_MONTHS = Array.from({ length: 12 }, (_, i) => `${YEAR}-${String(i + 1).padStart(2, "0")}`);

const round2 = (n: number) => Math.round(n * 100) / 100;
const season = (i: number) => 1 + 0.25 * Math.sin((Math.PI * (i - 3)) / 6); // summer-heavy

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

const PEAK_CUT = { timer: 2.5, with: 6.5 };

export function mockBacktestMonth(month: string, i: number): BacktestResult {
  const energyKwh = 21_000 * season(i);
  const peakWithout = 44 * season(i);
  return {
    dataset: "MOCK DATA, not a real dataset",
    month,
    policies: {
      without: mockBill(month, energyKwh, peakWithout),
      timer: mockBill(month, energyKwh, peakWithout - PEAK_CUT.timer),
      with: mockBill(month, energyKwh, peakWithout - PEAK_CUT.with),
    },
    checks: { baseline_matches_raw: true, energy_conserved: true, rule_violations: 0 },
    assumptions_id: "base",
  };
}

// ---------- load curves for the busiest day and the replay ----------

/** A restaurant day in kW (hour → kW), shaped like the live simulation: quiet night, lunch bump, dinner peak. */
const PROFILE: [number, number][] = [
  [0, 6], [6, 7], [8, 14], [10, 22], [12.5, 32], [15, 24], [17, 30], [19, 44], [21, 30], [23, 10], [24, 6],
];
function profileKw(hour: number) {
  for (let k = 1; k < PROFILE.length; k++) {
    const [h1, v1] = PROFILE[k];
    const [h0, v0] = PROFILE[k - 1];
    if (hour <= h1) return v0 + ((v1 - v0) * (hour - h0)) / (h1 - h0);
  }
  return PROFILE[PROFILE.length - 1][1];
}

/** Clip at `cap` and pay the owed energy back later, so each policy uses the same energy (energy_conserved). */
function shave(load: number[], cap: number) {
  let owed = 0;
  return load.map((kw) => {
    if (kw > cap) {
      owed += kw - cap;
      return cap;
    }
    const pay = Math.min(owed, cap - kw);
    owed -= pay;
    return kw + pay;
  });
}

/** UTC ms of a local Los Angeles wall time (PDT in Mar–Oct, PST otherwise; close enough for a mock). */
const localMs = (y: number, m: number, d: number, minutes: number) => Date.UTC(y, m, d, m >= 2 && m <= 9 ? 7 : 8, minutes);

function monthLoad(i: number, peakWithout: number) {
  const rand = mulberry32(1000 + i);
  const days = new Date(Date.UTC(YEAR, i + 1, 0)).getUTCDate();
  const ts: number[] = [];
  const raw: number[] = [];
  for (let d = 1; d <= days; d++) {
    const dow = new Date(Date.UTC(YEAR, i, d)).getUTCDay();
    const busy = (dow === 5 || dow === 6 ? 1.12 : 1) * (0.9 + 0.12 * rand());
    for (let s = 0; s < (24 * 60) / STEP_MIN; s++) {
      const hour = (s * STEP_MIN) / 60;
      const evening = hour >= 17 && hour <= 22 ? busy : 1;
      ts.push(localMs(YEAR, i, d, s * STEP_MIN));
      raw.push(profileKw(hour) * evening * (0.97 + 0.06 * rand()));
    }
  }
  // Scale so the month's highest 15-minute block is exactly the bill's peak.
  const top = Math.max(...raw);
  const without = raw.map((kw) => (kw * peakWithout) / top);
  return {
    ts,
    without,
    timer: shave(without, peakWithout - PEAK_CUT.timer),
    with: shave(without, peakWithout - PEAK_CUT.with),
  };
}

export function mockProofExtras(runId: string, results: BacktestResult[]): ProofExtras {
  const months = results.map((r, i) => ({
    month: r.month,
    partial: i === 0, // January is scored from day 22 (warm-up)
    saved_vs_without_usd: round2(r.policies.without.total_usd - r.policies.with.total_usd),
    saved_vs_timer_usd: round2(r.policies.timer.total_usd - r.policies.with.total_usd),
  }));
  const sum = (f: (r: BacktestResult) => number) => round2(results.reduce((a, r) => a + f(r), 0));
  const totals = {
    without_usd: sum((r) => r.policies.without.total_usd),
    timer_usd: sum((r) => r.policies.timer.total_usd),
    with_usd: sum((r) => r.policies.with.total_usd),
    saved_vs_without_usd: round2(months.reduce((a, m) => a + m.saved_vs_without_usd, 0)),
    saved_vs_timer_usd: round2(months.reduce((a, m) => a + m.saved_vs_timer_usd, 0)),
  };

  const replayResult = results[REPLAY_MONTH_INDEX];
  const load = monthLoad(REPLAY_MONTH_INDEX, replayResult.policies.without.demand_charges[0].peak_kw);

  // Busiest day: the day holding the month's top 15-minute block.
  const perDay = (24 * 60) / STEP_MIN;
  const peakIdx = load.without.indexOf(Math.max(...load.without));
  const dayStart = Math.floor(peakIdx / perDay) * perDay;
  const day = Array.from({ length: perDay }, (_, k) => dayStart + k);

  // Replay: hourly averages and each policy's running bill (energy so far + demand charge on the peak so far).
  const monthKwh = {
    without: load.without.reduce((a, kw) => a + kw * (STEP_MIN / 60), 0),
    timer: load.timer.reduce((a, kw) => a + kw * (STEP_MIN / 60), 0),
    with: load.with.reduce((a, kw) => a + kw * (STEP_MIN / 60), 0),
  };
  const steps: ProofExtras["replay"]["steps"] = [];
  const run = { without: { kwh: 0, peak: 0 }, timer: { kwh: 0, peak: 0 }, with: { kwh: 0, peak: 0 } };
  for (let k = 0; k < load.ts.length; k += 4) {
    const avg = { without: 0, timer: 0, with: 0 };
    for (const p of ["without", "timer", "with"] as const) {
      for (let j = k; j < k + 4; j++) {
        avg[p] += load[p][j] / 4;
        run[p].kwh += load[p][j] * (STEP_MIN / 60);
        run[p].peak = Math.max(run[p].peak, load[p][j]);
      }
    }
    // Energy so far as a share of the month's billed energy cost, so the last hour lands exactly on the table's bill.
    const bill = (p: keyof typeof run) =>
      round2((run[p].kwh / monthKwh[p]) * replayResult.policies[p].energy_cost_usd + run[p].peak * DEMAND_USD_PER_KW);
    steps.push({
      ts: new Date(load.ts[k]).toISOString(),
      without_kw: round2(avg.without),
      timer_kw: round2(avg.timer),
      with_kw: round2(avg.with),
      without_usd: bill("without"),
      timer_usd: bill("timer"),
      with_usd: bill("with"),
    });
  }

  const base = totals.saved_vs_without_usd;
  const SENS: [string, string, "assumptions" | "tariff", number][] = [
    ["base", "Base case", "assumptions", 1],
    ["low_flex", "Half the flexibility", "assumptions", 0.55],
    ["heavy_equipment", "Equipment draws 20 % more", "assumptions", 1.1],
    ["bad_forecast", "Forecast off by ±20 %", "assumptions", 0.8],
    ["tariff_b", "MOCK tariff B", "tariff", 0.7],
    ["tariff_c", "MOCK tariff C", "tariff", 1.25],
  ];
  const lowest = Math.min(...SENS.map((s) => s[3]));

  return {
    run_id: runId,
    tariff: { id: "mock-tariff", name: "MOCK tariff (the team records the real one in DECISIONS.md)" },
    audit: "cleared",
    months,
    totals,
    busiest_day: {
      date: new Date(load.ts[dayStart]).toISOString(),
      series: day.map((j) => ({ ts: new Date(load.ts[j]).toISOString(), without_kw: round2(load.without[j]), with_kw: round2(load.with[j]) })),
      peak_without_kw: round2(load.without[peakIdx]),
      peak_with_kw: round2(Math.max(...day.map((j) => load.with[j]))),
      peak_without_ts: new Date(load.ts[peakIdx]).toISOString(),
    },
    sensitivity: SENS.map(([id, label, kind, f]) => ({
      id,
      label,
      kind,
      saved_usd_year: round2(base * f),
      saved_pct: round2((100 * base * f) / totals.without_usd),
      worst: f === lowest,
    })),
    replay: { month: replayResult.month, steps },
  };
}
