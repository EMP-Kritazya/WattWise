// STUB: hand-transcribed from docs/CONTRACTS.md because the generated sources don't exist yet
// (contracts/ws_messages.schema.json and the API's /openapi.json). Once they do, run `npm run gen:types`,
// point src/types/index.ts at src/types/generated/, and delete this file. Never edit shapes here first:
// change docs/CONTRACTS.md (with the team) and regenerate.

// ---------- 1. Shared shapes ----------

export type Importance = "always_on" | "flexible" | "deferrable";

export type Category = "cooling" | "refrigeration" | "cooking" | "water_heating" | "lighting" | "other";

export type PowerModel = "fixed" | "cycling" | "thermal" | "demand_driven" | "job";

export interface EquipmentType {
  type_id: string;
  name: string;
  category: Category;
  default_importance: Importance;
  rated_kw: number;
  min_power_pct: number | null;
  power_model: PowerModel;
  params: Record<string, unknown>;
  source_note: string;
}

export interface FlexibleLimits {
  min_power_pct: number;
  max_reduce_min: number;
}

export interface DeferrableLimits {
  max_delay_min: number;
  /** Local time "HH:MM". */
  must_finish_by: string;
}

/** `{}` for always_on, FlexibleLimits for flexible, DeferrableLimits for deferrable. */
export type ImportanceLimits = Record<string, never> | FlexibleLimits | DeferrableLimits;

export interface EquipmentEntry {
  type_id: string;
  /** 0 = not in this kitchen. Each unit becomes a Device `<type_id>_<n>`. */
  count: number;
  importance: Importance;
  limits: ImportanceLimits;
}

export interface KitchenConfig {
  name: string;
  equipment: EquipmentEntry[];
  peak_cap_kw: number;
  operating_hours: { open: string; close: string };
  tariff_id: string;
  seed: number;
}

export type DeviceState = "off" | "on" | "reduced" | "waiting" | "running_job";

export interface Device {
  device_id: string;
  type_id: string;
  name: string;
  importance: Importance;
  state: DeviceState;
  power_kw: number;
  rated_kw: number;
  source: "simulated";
}

export interface HubDeviceReading {
  device_id: string;
  power_kw: number;
  state: DeviceState;
}

export interface HubReport {
  ts: string;
  total_kw: number;
  devices: HubDeviceReading[];
  source: "simulated";
}

export type CommandAction = "on" | "off" | "start" | "delay" | "reduce" | "restore";

export interface Command {
  command_id: string;
  ts: string;
  device_id: string;
  action: CommandAction;
  /** Minutes for `delay`, power % for `reduce`. */
  value: number | null;
  decision_id: string | null;
  issued_by: "engine" | "owner";
}

export type DecisionStatus = "executed" | "awaiting_approval" | "approved" | "declined" | "expired" | "undone";

export type ReasonCode = "avoid_new_peak" | "stay_under_cap" | "release_into_valley" | "catch_up" | "owner_override";

export interface Effect {
  peak_before_kw: number;
  peak_after_kw: number;
  saving_usd: number;
}

export interface Decision {
  decision_id: string;
  ts: string;
  device_id: string;
  action: CommandAction;
  value: number | null;
  reason_code: ReasonCode;
  inside_rules: boolean;
  status: DecisionStatus;
  effect: Effect;
}

export interface Meter {
  ts: string;
  total_kw: number;
  block_avg_kw: number;
  block_start: string;
  month_peak_kw: number;
  peak_cap_kw: number;
  energy_kwh_today: number;
  cost_usd_today: number;
  cost_usd_month: number;
}

export type Lane = "without" | "with";

export interface TickState {
  lane: Lane;
  ts: string;
  hub: HubReport;
  meter: Meter;
  customers_per_hour: number;
  new_decisions: Decision[];
  /** Next 2 h in 15-min steps; only on re-plan ticks, otherwise null. */
  forecast_kw: number[] | null;
}

export interface DemandCharge {
  name: string;
  peak_kw: number;
  cost_usd: number;
}

export interface Bill {
  period: string;
  energy_kwh: number;
  energy_cost_usd: number;
  demand_charges: DemandCharge[];
  total_usd: number;
  tariff_id: string;
}

export interface BacktestResult {
  dataset: string;
  month: string;
  policies: { without: Bill; timer: Bill; with: Bill };
  checks: { baseline_matches_raw: boolean; energy_conserved: boolean; rule_violations: number };
  assumptions_id: string;
}

// ---------- 2. Seam 1: REST bodies ----------

/** UNCLEAR in CONTRACTS.md: "KitchenConfig + list[Device]". Assumed to match snapshot()'s `{ config, devices }`. */
export interface KitchenView {
  config: KitchenConfig;
  devices: Device[];
}

export interface ImportanceUpdate {
  importance: Importance;
  limits: ImportanceLimits;
}

export interface SimControlRequest {
  action: "play" | "pause" | "reset";
  speed?: number;
}

/** UNCLEAR in CONTRACTS.md ("clock state"). Assumed to match the `clock` WebSocket message. */
export interface ClockState {
  playing: boolean;
  speed: number;
  sim_ts: string;
  paused_reason: string | null;
}

export interface DeviceCommandRequest {
  action: CommandAction;
  value?: number;
}

export interface CustomerEventRequest {
  customers: number;
  duration_min: number;
}

export interface BacktestRunRequest {
  /** UNCLEAR in CONTRACTS.md: a list of "YYYY-MM" months or a count. */
  months: string[] | number;
  assumptions_id: string;
}

// ---------- 2. Seam 1: WebSocket /ws (server → client) ----------

export type WsMessage =
  | { type: "tick"; data: TickState }
  | { type: "decision"; data: Decision; explanation: string; explanation_source: "ai" | "template" }
  | { type: "approval_request"; data: Decision; explanation: string; expires_at: string }
  | ({ type: "clock" } & ClockState)
  | { type: "warning"; code: "cap_unreachable" | (string & {}); message: string; data: Record<string, unknown> }
  | { type: "chat_delta"; chat_id: string; text: string }
  | { type: "chat_done"; chat_id: string }
  | { type: "backtest_progress"; run_id: string; month: string; pct: number };

export type WsMessageType = WsMessage["type"];
