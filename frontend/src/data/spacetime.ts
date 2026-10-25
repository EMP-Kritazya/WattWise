import type {
  Escalation,
  LiveAgentLogRow,
  LiveClockRow,
  LiveComparisonRow,
  LiveDeviceRow,
  LiveEscalationRow,
  LiveFeedRow,
  LiveTickRow,
  TickState,
  WsMessage,
} from "@/types";

// SpacetimeDB live source (CONTRACTS.md section 5). The runtime publishes the shared kitchen into tables; every viewer
// subscribes, so a judge's phone and the projector see the same kitchen. Rows are converted into the same messages
// `/ws` sends, so the store and every screen work unchanged whichever source is live.

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
      hub_id: "sim_hub",
      lane: tick.lane,
      tick_id: tick.tick_id,
      ts: tick.ts,
      total_kw: tick.total_kw,
      customers_per_hour: tick.customers_per_hour,
      devices: mine.map((d) => ({
        device_id: d.device_id,
        type_id: d.type_id,
        name: d.name,
        importance: d.importance,
        state: d.state,
        power_kw: d.power_kw,
        rated_kw: d.rated_kw,
        power_pct: d.power_pct,
        source: d.source,
        physical: parse(d.physical_json, undefined),
      })),
      acks: [],
      source: mine.some((d) => d.source === "measured") ? "mixed" : "simulated",
    },
    meter: {
      ts: tick.ts,
      total_kw: tick.total_kw,
      block_avg_kw: tick.block_avg_kw,
      block_start: prev?.meter.block_start ?? tick.ts,
      month_peak_kw: tick.month_peak_kw,
      peak_mode: tick.peak_mode,
      peak_cap_kw: tick.peak_cap_kw,
      target_kw: tick.target_kw,
      energy_kwh_today: tick.energy_kwh_today,
      price_usd_per_kwh_now: tick.price_usd_per_kwh_now,
      cost_usd_today: tick.cost_usd_today,
      cost_usd_month: tick.cost_usd_month,
    },
    customers_per_hour: tick.customers_per_hour,
    new_decisions: [],
    forecast_kw: parse<number[] | null>(tick.forecast_kw_json, null),
  };
  return { type: "tick", data };
}

export const comparisonMessage = ({ id: _id, ...data }: LiveComparisonRow): WsMessage => ({ type: "comparison", data });

export const feedMessage = (row: LiveFeedRow): WsMessage => ({
  type: "decision",
  data: {
    decision_id: row.decision_id,
    ts: row.ts,
    device_id: row.device_id,
    action: row.action,
    value: row.value,
    reason_code: row.reason_code,
    inside_rules: true,
    status: row.status,
    effect: parse(row.effect_json, { peak_before_kw: 0, peak_after_kw: 0, saving_usd: 0 }),
  },
  explanation: row.explanation,
  explanation_source: row.explanation_source,
});

export const clockMessage = ({ id: _id, sim_host: _simHost, ...clock }: LiveClockRow): WsMessage => ({ type: "clock", ...clock });

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

export const agentLogMessage = ({ id: _id, ...data }: LiveAgentLogRow): WsMessage => ({ type: "agent_log", data });

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
