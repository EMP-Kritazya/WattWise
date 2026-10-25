import { describe, expect, it } from "vitest";
import backtestPointTable from "@fixtures/spacetime/tables/backtest_point.json";
import backtestMonthTable from "@fixtures/spacetime/tables/backtest_month.json";
import type { BacktestMonthRow, BacktestPointRow } from "@/types";
import { buildProofChart, markLabel, tariffLabel } from "./proofChart";

const points = backtestPointTable as unknown as BacktestPointRow[];
const months = backtestMonthTable as unknown as BacktestMonthRow[];
const fmt = (usd: number) => `$${usd.toFixed(2)}`;

describe("buildProofChart (fixture rows: fake data, never savings)", () => {
  const chart = buildProofChart(points, months, fmt);

  it("copies every day's saved_month_to_date_usd unchanged, in day order", () => {
    const drawn = chart.line.filter((p) => p.saved !== null);
    expect(drawn).toHaveLength(points.length);
    const byDay = new Map(points.map((p) => [p.day, p.saved_month_to_date_usd]));
    for (const p of drawn) expect(p.saved).toBe(byDay.get(p.day!));
    expect(drawn.map((p) => p.day)).toEqual([...points.map((p) => p.day)].sort());
  });

  it("breaks the line between months and places days on a 12-month axis", () => {
    const breaks = chart.line.filter((p) => p.saved === null);
    expect(breaks).toHaveLength(1); // June -> July
    expect(breaks[0].x).toBe(6); // start of July (index 6)
    const june30 = chart.line.find((p) => p.day === "2026-06-30")!;
    expect(june30.x).toBe(6); // end of June
    expect(chart.domain).toEqual([0, 12]);
    expect(chart.ticks).toHaveLength(12);
    expect(chart.tickLabel(0.5)).toBe("Jan");
    expect(chart.tickLabel(6.5)).toBe("Jul");
  });

  it("puts one mark per month at the month's last point, labelled with the published saved_usd", () => {
    expect(chart.marks.map((m) => m.month)).toEqual(["2026-06", "2026-07"]);
    for (const m of chart.marks) {
      const row = months.find((r) => r.month === m.month)!;
      expect(m.saved_usd).toBe(row.saved_usd);
      const lastPoint = [...points].filter((p) => p.month === m.month).sort((a, b) => a.day.localeCompare(b.day)).pop()!;
      expect(m.saved_usd).toBe(lastPoint.saved_month_to_date_usd); // engine guarantee, checked, not computed
      expect(m.label.startsWith(fmt(row.saved_usd))).toBe(true);
    }
  });

  it("labels partial months; the first one as warm-up", () => {
    expect(markLabel("2026-01", true, "$1.00", "2026-01")).toBe("$1.00 · partial (warm-up)");
    expect(markLabel("2026-12", true, "$1.00", "2026-01")).toBe("$1.00 · partial");
    expect(markLabel("2026-05", false, "$1.00", "2026-01")).toBe("$1.00");
  });

  it("shows tariff names with their honesty label", () => {
    expect(tariffLabel("pge_b19_secondary_voluntary")).toContain("urdb");
    expect(tariffLabel("demo_tariff_v1")).toContain("illustrative");
  });
});
