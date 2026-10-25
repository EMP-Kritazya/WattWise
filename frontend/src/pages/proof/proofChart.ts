// Proof chart shaping (UI.md section 4; Mode A). Pure: places published rows on a 12-month axis. Every $ value is copied
// from a row as published (BacktestPoint.saved_month_to_date_usd, BacktestResult.saved_usd); nothing here adds, subtracts or
// multiplies money. The only arithmetic is the x position (calendar placement).
import type { BacktestMonthRow, BacktestPointRow } from "@/types";

export const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export interface LinePoint {
  /** months since January of the first row's year; day d of a month sits at monthIndex + d / daysInMonth (end of day). */
  x: number;
  /** saved_month_to_date_usd as published; null breaks the line at a month boundary. */
  saved: number | null;
  day: string | null;
  ytd: number | null;
}

export interface MonthMark {
  month: string;
  x: number;
  saved_usd: number;
  saved_vs_timer_usd: number;
  partial: boolean;
  label: string;
}

export interface ProofChart {
  year: number;
  line: LinePoint[];
  marks: MonthMark[];
  domain: [number, number];
  ticks: number[];
  tickLabel: (x: number) => string;
}

const ym = (month: string) => ({ y: Number(month.slice(0, 4)), m: Number(month.slice(5, 7)) });
const daysIn = (y: number, m: number) => new Date(Date.UTC(y, m, 0)).getUTCDate();

/** Text next to a month mark: the engine's saved_usd, formatted, plus the partial note (January: warm-up). */
export function markLabel(month: string, partial: boolean, savedText: string, firstMonth: string): string {
  if (!partial) return savedText;
  return month === firstMonth ? `${savedText} · partial (warm-up)` : `${savedText} · partial`;
}

export function buildProofChart(points: BacktestPointRow[], months: BacktestMonthRow[], fmt: (usd: number) => string): ProofChart {
  const all = [...points.map((p) => p.month), ...months.map((m) => m.month)].sort();
  const year = all.length ? ym(all[0]).y : new Date().getUTCFullYear();
  const index = (month: string) => {
    const { y, m } = ym(month);
    return (y - year) * 12 + (m - 1);
  };
  const xOfDay = (day: string) => {
    const y = Number(day.slice(0, 4));
    const m = Number(day.slice(5, 7));
    const d = Number(day.slice(8, 10));
    return index(day.slice(0, 7)) + d / daysIn(y, m);
  };

  const sorted = [...points].sort((a, b) => a.day.localeCompare(b.day));
  const line: LinePoint[] = [];
  const lastX = new Map<string, number>();
  let prevMonth: string | null = null;
  for (const p of sorted) {
    if (prevMonth !== null && p.month !== prevMonth) {
      line.push({ x: index(p.month), saved: null, day: null, ytd: null }); // the month-to-date line restarts each month
    }
    const x = xOfDay(p.day);
    line.push({ x, saved: p.saved_month_to_date_usd, day: p.day, ytd: p.saved_year_to_date_usd });
    lastX.set(p.month, x);
    prevMonth = p.month;
  }

  const firstMonth = all[0] ?? "";
  const marks: MonthMark[] = [...months]
    .sort((a, b) => a.month.localeCompare(b.month))
    .map((r) => ({
      month: r.month,
      x: lastX.get(r.month) ?? index(r.month) + 1,
      saved_usd: r.saved_usd,
      saved_vs_timer_usd: r.saved_vs_timer_usd,
      partial: r.partial,
      label: markLabel(r.month, r.partial, fmt(r.saved_usd), firstMonth),
    }));

  const last = all.length ? index(all[all.length - 1]) + 1 : 12;
  const end = Math.max(12, last);
  const ticks = Array.from({ length: end }, (_, i) => i + 0.5);
  const tickLabel = (x: number) => {
    const i = Math.floor(x);
    const name = MONTH_NAMES[((i % 12) + 12) % 12];
    return i >= 12 ? `${name} ${year + Math.floor(i / 12)}` : name;
  };
  return { year, line, marks, domain: [0, end], ticks, tickLabel };
}

/** Display name of the tariff a run used (labels only; numbers never come from here). */
export function tariffLabel(tariffId: string | undefined): string {
  switch (tariffId) {
    case "pge_b19_secondary_voluntary":
      return "PG&E B-19 Medium General Demand TOU (Secondary) Voluntary · urdb";
    case "demo_tariff_v1":
      return "WattWise demo commercial rate · illustrative";
    default:
      return tariffId ?? "–";
  }
}
