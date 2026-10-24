import type { DeviceState, Escalation, Lane, TickState, WsMessage } from "@/types";

// SpacetimeDB live source (CONTRACTS.md section 5). The runtime publishes the shared kitchen into tables; every viewer
// subscribes, so a judge's phone and the projector see the same kitchen. Rows are converted into the same messages
// `/ws` sends, so the store and every screen work unchanged whichever source is live.

/** Row shapes as listed in CONTRACTS.md section 5 (JSON columns arrive as strings). */
export interface LiveTickRow {
  lane: Lane;
  ts: string;
  total_kw: number;
  block_avg_kw: number;
  month_peak_kw: number;
  peak_cap_kw: number;
  cost_usd_today: number;
  customers_per_hour: number;
  forecast_kw_json: string | null;
}
export interface LiveDeviceRow {
  lane: Lane;
  device_id: string;
  name: string;
  importance: string;
  state: DeviceState;
  power_kw: number;
  source: "simulated" | "measured";
}
export interface LiveComparisonRow {
  ts: string;
  saved_today_usd: number;
  peak_avoided_kw: number;
  month_peak_without_kw: number;
  month_peak_with_kw: number;
}
export interface LiveFeedRow {
  decision_id: string;
  lane: Lane;
  ts: string;
  device_id: string;
  action: string;
  value: number | null;
  status: string;
  reason_code: string;
  effect_json: string;
  explanation: string;
  explanation_source: "ai" | "template";
}
export interface LiveClockRow {
  playing: boolean;
  speed: number;
  sim_ts: string;
  paused_reason: string | null;
}
export interface LiveEscalationRow {
  escalation_id: string;
  lane: Lane;
  status: Escalation["status"];
  problem_json: string;
  options_json: string;
  chosen_option_id: string | null;
  resolved_by: Escalation["resolved_by"];
  rationale: string | null;
}
export interface LiveAgentLogRow {
  ts_real: string;
  from_agent: string;
  to_agent: string;
  kind: string;
  summary: string;
}

const parse = <T,>(json: string | null | undefined, fallback: T): T => {
  if (!json) return fallback;
  try {
    return JSON.parse(json) as T;
  } catch {
    return fallback;
  }
};

/**
 * live_tick + that lane's live_device rows → a `tick` message. live_tick carries the meter's headline fields only;
 * fields it doesn't have (energy today, month cost, block start) are left at what's knowable, never computed here.
 */
export function tickMessage(tick: LiveTickRow, devices: LiveDeviceRow[], prev?: TickState | null): WsMessage {
  const mine = devices.filter((d) => d.lane === tick.lane);
  const data: TickState = {
    lane: tick.lane,
    ts: tick.ts,
    hub: {
      ts: tick.ts,
      total_kw: tick.total_kw,
      devices: mine.map((d) => ({ device_id: d.device_id, power_kw: d.power_kw, state: d.state, source: d.source })),
      source: mine.some((d) => d.source === "measured") ? "mixed" : "simulated",
    },
    meter: {
      ts: tick.ts,
      total_kw: tick.total_kw,
      block_avg_kw: tick.block_avg_kw,
      block_start: prev?.meter.block_start ?? tick.ts,
      month_peak_kw: tick.month_peak_kw,
      peak_cap_kw: tick.peak_cap_kw,
      energy_kwh_today: prev?.meter.energy_kwh_today ?? 0,
      cost_usd_today: tick.cost_usd_today,
      cost_usd_month: prev?.meter.cost_usd_month ?? 0,
    },
    customers_per_hour: tick.customers_per_hour,
    new_decisions: [],
    forecast_kw: parse<number[] | null>(tick.forecast_kw_json, null),
  };
  return { type: "tick", data };
}

export const comparisonMessage = (row: LiveComparisonRow): WsMessage => ({ type: "comparison", data: { ...row } });

export const feedMessage = (row: LiveFeedRow): WsMessage => ({
  type: "decision",
  data: {
    decision_id: row.decision_id,
    ts: row.ts,
    device_id: row.device_id,
    action: row.action as never,
    value: row.value,
    reason_code: row.reason_code as never,
    inside_rules: row.status !== "escalated",
    status: row.status as never,
    effect: parse(row.effect_json, { peak_before_kw: 0, peak_after_kw: 0, saving_usd: 0 }),
  },
  explanation: row.explanation,
  explanation_source: row.explanation_source,
});

export const clockMessage = (row: LiveClockRow): WsMessage => ({ type: "clock", ...row });

export const escalationMessage = (row: LiveEscalationRow, prev?: Escalation): WsMessage => {
  const problem = parse(row.problem_json, prev?.problem ?? { forecast_peak_kw: 0, target_kw: 0, excess_kw: 0, reason: "" });
  return {
    type: "escalation",
    data: {
      escalation_id: row.escalation_id,
      lane: row.lane,
      ts: prev?.ts ?? "",
      block_start: prev?.block_start ?? "",
      problem,
      options: parse(row.options_json, prev?.options ?? []),
      default_option_id: prev?.default_option_id ?? "",
      deadline_sim_ts: prev?.deadline_sim_ts ?? "",
      status: row.status,
      resolved_by: row.resolved_by,
      chosen_option_id: row.chosen_option_id,
      rationale: row.rationale,
    },
  };
};

export const agentLogMessage = (row: LiveAgentLogRow): WsMessage => ({ type: "agent_log", data: { ...row } });

export class SpacetimeUnavailable extends Error {}

export interface SpacetimeConfig {
  uri: string;
  database: string;
}

/**
 * Subscribe to the live tables and call `onMessages` with converted messages. Returns a stop function.
 * STUB: needs Kritazya's generated SpacetimeDB TypeScript bindings (`spacetime generate`) and the `spacetimedb` SDK.
 * When they land: connect with the bindings' DbConnection, subscribe to the section 5 tables, and on every insert or
 * update call the mappers above. Until then this throws and the app falls back to `/ws`.
 */
export async function connectSpacetime(
  _config: SpacetimeConfig,
  _onMessages: (msgs: WsMessage[]) => void,
  _onStatus: (status: "connecting" | "open" | "closed") => void,
): Promise<() => void> {
  throw new SpacetimeUnavailable("SpacetimeDB bindings are not generated yet");
}

/** The `request_surge` reducer (anyone may call it). STUB with connectSpacetime. */
export async function callRequestSurge(_customers: number, _durationMin: number): Promise<void> {
  throw new SpacetimeUnavailable("SpacetimeDB bindings are not generated yet");
}
