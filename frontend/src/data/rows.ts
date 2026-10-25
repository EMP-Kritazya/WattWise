// Section 5 row builders in the browser: the same mapping as backend/live/rows.py, used when the live source is /ws or
// the fixture mock (so screens read one row shape whatever the source). Numbers are copied, never computed.
import type {
  BacktestMonthRow,
  BacktestPoint,
  BacktestPointRow,
  BacktestResult,
  Context,
  Escalation,
  LiveContextRow,
  LiveDeviceRow,
  LiveEscalationRow,
  LiveFeedRow,
  LiveTickRow,
  TickHistoryRow,
  TickState,
  Decision,
  Lane,
} from "@/types";

const cj = (value: unknown): string => JSON.stringify(value);

export function liveTickRow(tick: TickState, forecast: number[] | null, forecastTs: string | null): LiveTickRow {
  const m = tick.meter;
  return {
    lane: tick.lane,
    ts: tick.ts,
    tick_id: tick.hub.tick_id,
    total_kw: m.total_kw,
    block_avg_kw: m.block_avg_kw,
    month_peak_kw: m.month_peak_kw,
    on_peak_month_peak_kw: m.on_peak_month_peak_kw ?? null,
    peak_mode: m.peak_mode,
    peak_cap_kw: m.peak_cap_kw,
    target_kw: m.target_kw,
    energy_kwh_today: m.energy_kwh_today,
    energy_kwh_month: m.energy_kwh_month ?? 0,
    price_usd_per_kwh_now: m.price_usd_per_kwh_now,
    cost_usd_today: m.cost_usd_today,
    cost_usd_month: m.cost_usd_month,
    demand_peaks_json: cj(m.demand_peaks ?? []),
    customers_per_hour: tick.customers_per_hour,
    indoor_temp_c: tick.indoor_temp_c ?? 0,
    forecast_kw_json: forecast ? cj(forecast) : null,
    forecast_ts: forecast ? forecastTs : null,
  };
}

export const tickHistoryRow = (tick: TickState): TickHistoryRow => ({
  lane: tick.lane,
  ts: tick.ts,
  total_kw: tick.meter.total_kw,
  block_avg_kw: tick.meter.block_avg_kw,
});

export const liveDeviceRows = (tick: TickState): LiveDeviceRow[] =>
  tick.hub.devices.map((device) => ({
    key: `${tick.lane}:${device.device_id}`,
    lane: tick.lane,
    device_id: device.device_id,
    type_id: device.type_id,
    name: device.name,
    importance: device.importance,
    state: device.state,
    power_kw: device.power_kw,
    rated_kw: device.rated_kw,
    power_pct: device.power_pct,
    source: device.source,
    physical_json: device.physical ? cj(device.physical) : null,
  }));

export const feedRow = (
  decision: Decision,
  lane: Lane,
  explanation: string,
  explanationSource: "ai" | "template",
): LiveFeedRow => ({
  decision_id: decision.decision_id,
  lane,
  ts: decision.ts,
  device_id: decision.device_id,
  action: decision.action,
  value: decision.value,
  status: decision.status,
  reason_code: decision.reason_code,
  effect_json: cj(decision.effect),
  explanation,
  explanation_source: explanationSource,
});

/** Template fallback contains only the engine verdict; AI explanations arrive verbatim over the transport. */
function escalationExplanation(e: Escalation): string {
  const last = e.claude_attempts?.at(-1);
  if (last && !last.accepted) return `Claude's choice rejected: ${last.reason}. Engine fallback remains active.`;
  return e.status === "resolved" ? "Claude's choice accepted." : "Engine fallback remains active.";
}

export const escalationRow = (
  e: Escalation,
  explanation = e.explanation ?? escalationExplanation(e),
  explanationSource: "ai" | "template" = e.explanation_source ?? "template",
): LiveEscalationRow => ({
  escalation_id: e.escalation_id,
  lane: e.lane,
  status: e.status,
  block_start: e.block_start,
  updated_ts: e.updated_ts ?? e.ts,
  problem_json: cj(e.problem),
  options_json: cj(e.options),
  default_option_id: e.default_option_id,
  active_option_id: e.active_option_id ?? null,
  deadline_sim_ts: e.deadline_sim_ts,
  chosen_option_id: e.chosen_option_id,
  resolved_by: e.resolved_by,
  rationale: e.rationale,
  claude_attempts_json: cj(e.claude_attempts ?? []),
  explanation,
  explanation_source: explanationSource,
});

/** Same summary text as backend/live/rows.py context_row (numbers as the agents posted them). */
export function contextRow(c: Context): LiveContextRow {
  const weather = c.weather?.hourly?.[0];
  const price = c.prices?.hourly?.[0];
  const events = (c.events?.items ?? []).map((i) => `${i.name} at ${i.venue}, ${i.distance_km.toFixed(1)} km`).join("; ");
  return {
    id: 0,
    weather_summary: weather ? `${weather.temp_c.toFixed(1)} °C now` : "Weather unavailable",
    weather_label: c.weather?.label ?? "recorded",
    prices_summary: price ? `${price.usd_per_kwh.toFixed(2)} USD/kWh now, stress ${c.prices?.stress}` : "Prices unavailable",
    prices_label: c.prices?.label ?? "recorded",
    events_summary: events || "No events nearby",
    events_label: c.events?.label ?? "recorded",
    crowd_effect: c.crowd_effect?.value ?? "none",
  };
}

export const backtestPointRow = (runId: string, p: BacktestPoint): BacktestPointRow => ({
  key: `${runId}:${p.day}`,
  run_id: runId,
  day: p.day,
  month: p.month,
  ts: p.ts,
  partial: p.partial,
  cost_to_date_json: cj(p.cost_to_date_usd),
  saved_month_to_date_usd: p.saved_month_to_date_usd,
  saved_vs_timer_month_to_date_usd: p.saved_vs_timer_month_to_date_usd,
  saved_year_to_date_usd: p.saved_year_to_date_usd,
  dataset: p.dataset,
  tariff_id: p.tariff_id,
  assumptions_id: p.assumptions_id,
});

export const backtestMonthRow = (runId: string, r: BacktestResult): BacktestMonthRow => ({
  key: `${runId}:${r.month}`,
  run_id: runId,
  month: r.month,
  partial: r.partial,
  saved_usd: r.saved_usd,
  saved_vs_timer_usd: r.saved_vs_timer_usd,
  policies_json: cj(r.policies),
  checks_json: cj(r.checks),
  dataset: r.dataset,
  tariff_id: r.tariff_id,
  assumptions_id: r.assumptions_id,
});

/** Row -> BacktestPoint (parses cost_to_date_json). */
export const backtestPointOf = (row: BacktestPointRow): BacktestPoint => ({
  dataset: row.dataset,
  assumptions_id: row.assumptions_id,
  tariff_id: row.tariff_id,
  month: row.month,
  day: row.day,
  ts: row.ts,
  partial: row.partial,
  cost_to_date_usd: JSON.parse(row.cost_to_date_json),
  saved_month_to_date_usd: row.saved_month_to_date_usd,
  saved_vs_timer_month_to_date_usd: row.saved_vs_timer_month_to_date_usd,
  saved_year_to_date_usd: row.saved_year_to_date_usd,
});

/** Row -> BacktestResult (parses policies_json and checks_json). */
export const backtestMonthOf = (row: BacktestMonthRow): BacktestResult => ({
  dataset: row.dataset,
  month: row.month,
  policies: JSON.parse(row.policies_json),
  checks: JSON.parse(row.checks_json),
  assumptions_id: row.assumptions_id,
  tariff_id: row.tariff_id,
  partial: row.partial,
  saved_usd: row.saved_usd,
  saved_vs_timer_usd: row.saved_vs_timer_usd,
});

/** Upsert rows by key, keeping only the newest run (a new run_id replaces the old run's rows: "latest run only"). */
export function upsertRun<T extends { key: string; run_id: string }>(rows: T[], additions: T[]): T[] {
  if (!additions.length) return rows;
  const runId = additions[additions.length - 1].run_id;
  const map = new Map(rows.filter((r) => r.run_id === runId).map((r) => [r.key, r]));
  additions.filter((r) => r.run_id === runId).forEach((r) => map.set(r.key, r));
  return [...map.values()];
}
