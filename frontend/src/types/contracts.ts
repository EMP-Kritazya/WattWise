// STUB: replace with generated OpenAPI, WebSocket-schema, and SpacetimeDB types.
// Hand-transcribed from docs/CONTRACTS.md while those generated sources do not exist.

// STUB: replace with generated shared-shape types.
export type Importance = "always_on" | "flexible" | "deferrable";
export type Category = "cooling" | "refrigeration" | "cooking" | "water_heating" | "lighting" | "other";
export type PowerModel = "fixed" | "cycling" | "thermal" | "demand_driven" | "job";
export type Lane = "without" | "with";
export type DataLabel = "live_api" | "recorded";

export interface FlexibleLimits {
  min_power_pct: number;
  max_reduce_min: number;
}
export interface DeferrableLimits {
  max_delay_min: number;
  /** Local time, HH:MM. */
  must_finish_by: string;
}
export type ImportanceLimits = Record<string, never> | FlexibleLimits | DeferrableLimits;
export type EquipmentParams =
  | Record<string, never>
  | { duty_idle_pct: number; duty_busy_pct: number }
  | { setpoint_c: number }
  | { idle_kw: number; kw_per_order: number }
  | { cycle_min: number };

export interface EquipmentType {
  type_id: string;
  name: string;
  category: Category;
  default_importance: Importance;
  rated_kw: number;
  power_model: PowerModel;
  params: EquipmentParams;
  default_limits: ImportanceLimits;
  source_note: string;
}
export interface EquipmentEntry {
  type_id: string;
  count: number;
  importance: Importance;
  limits: ImportanceLimits;
}
export interface ClaudeAuthority {
  enabled: boolean;
  max_cap_overrun_kw: number;
  max_extra_delay_min: number;
  max_extra_reduce_min: number;
  may_go_below_min_power: boolean;
}
export interface KitchenConfig {
  name: string;
  equipment: EquipmentEntry[];
  peak_mode: "minimize" | "cap";
  peak_cap_kw: number | null;
  operating_hours: { open: string; close: string };
  location: { lat: number; lon: number; label: string };
  owner_preferences: string;
  authority: ClaudeAuthority;
  tariff_id: string;
  seed: number;
}
export interface Tariff {
  tariff_id: string;
  name: string;
  label: "illustrative" | "urdb";
  currency: string;
  timezone: string;
  energy: { name: string; start: string; end: string; usd_per_kwh: number }[];
  demand: { name: string; window: { start: string; end: string } | null; usd_per_kw: number }[];
}

export type DeviceState = "off" | "on" | "reduced" | "waiting" | "running_job";
export type DevicePhysical = Partial<{
  indoor_temp_c: number;
  box_temp_c: number;
  dirty_racks: number;
  ice_level_pct: number;
  job_remaining_min: number;
  orders_in_progress: number;
}> & Record<string, unknown>;
export interface Device {
  device_id: string;
  type_id: string;
  name: string;
  importance: Importance;
  state: DeviceState;
  power_kw: number;
  rated_kw: number;
  power_pct: number;
  source: "simulated" | "measured";
  physical?: DevicePhysical;
}
/** UI compatibility name. HubReport carries full Device objects in the current contract. */
export type HubDeviceReading = Device;
export interface CommandAck {
  command_id: string;
  lane: Lane;
  ok: boolean;
  applied_value: number | null;
  reason: "out_of_range" | "job_running" | "already_off" | "unknown_device" | null;
}
export interface HubReport {
  hub_id: string;
  lane: Lane;
  tick_id: number;
  ts: string;
  total_kw: number;
  customers_per_hour: number;
  devices: Device[];
  acks: CommandAck[];
  source: "simulated" | "mixed";
}
export interface Reading {
  hub_id: string;
  channel: number;
  device_id: string;
  ts: string;
  raw_w: number;
  scale: number;
  power_kw: number;
}
export type CommandAction = "on" | "off" | "start" | "delay" | "reduce" | "restore";
export interface Command {
  command_id: string;
  lane: Lane;
  ts: string;
  device_id: string;
  action: CommandAction;
  value: number | null;
  decision_id: string | null;
  issued_by: "engine" | "owner";
}
export type DecisionStatus = "executed" | "undone";
export type ReasonCode =
  | "avoid_new_peak"
  | "stay_under_cap"
  | "release_into_valley"
  | "catch_up"
  | "owner_override"
  | "escalation_choice";
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
export interface Context {
  ts: string;
  weather?: { label: DataLabel; source: string; hourly: { ts: string; temp_c: number }[] };
  prices?: { label: DataLabel; source: string; hourly: { ts: string; usd_per_kwh: number }[]; stress: "low" | "normal" | "high" };
  events?: {
    label: DataLabel;
    source: string;
    items: { name: string; venue: string; start: string; distance_km: number; expected_attendance: number }[];
  };
  crowd_effect?: { value: "none" | "small" | "medium" | "large"; set_by: "claude" | "owner" | "default"; reason: string };
}
export interface RuleBreak {
  kind: "cap_overrun" | "below_min_power" | "past_deadline" | "over_max_reduce" | "over_max_delay";
  device_id?: string;
  amount: number;
  unit: string;
}
export interface EscalationOption {
  option_id: string;
  summary: string;
  actions: Command[];
  projected: { peak_kw: number; cost_delta_usd: number; max_indoor_temp_change_c: number | null };
  rule_breaks: RuleBreak[];
  within_authority: boolean;
  harm_score: number;
  rank: number;
}
export type EscalationStatus = "open" | "resolved" | "expired_default" | "obsolete";
export interface ClaudeAttempt {
  ts: string;
  option_id: string;
  accepted: boolean;
  reason: "outside_authority" | "after_deadline" | null;
  rationale: string | null;
}
export interface Escalation {
  escalation_id: string;
  lane: Lane;
  ts: string;
  block_start: string;
  problem: { forecast_peak_kw: number; target_kw: number; excess_kw: number; reason: string };
  options: EscalationOption[];
  default_option_id: string;
  active_option_id: string | null;
  updated_ts: string;
  deadline_sim_ts: string;
  status: EscalationStatus;
  resolved_by: "claude" | "default" | null;
  chosen_option_id: string | null;
  rationale: string | null;
  claude_attempts: ClaudeAttempt[];
  /** Notification text supplied by /ws or live_escalation, not computed by the screen. */
  explanation?: string;
  explanation_source?: "ai" | "template";
}
export interface Meter {
  ts: string;
  total_kw: number;
  block_avg_kw: number;
  block_start: string;
  month_peak_kw: number;
  /** Month peak of the highest-rate windowed demand charge that applies this month; null if none (CONTRACTS.md Meter). */
  on_peak_month_peak_kw?: number | null;
  peak_mode: "minimize" | "cap";
  peak_cap_kw: number | null;
  target_kw: number;
  energy_kwh_today: number;
  energy_kwh_month?: number;
  price_usd_per_kwh_now: number;
  cost_usd_today: number;
  cost_usd_month: number;
  /** One entry per demand charge that applies this month, tariff order; engine-computed cost (the UI never multiplies). */
  demand_peaks?: DemandPeak[];
}
export interface DemandPeak {
  name: string;
  peak_kw: number;
  usd_per_kw: number;
  cost_usd: number;
}
export interface TickState {
  lane: Lane;
  ts: string;
  hub: HubReport;
  meter: Meter;
  customers_per_hour: number;
  new_decisions: Decision[];
  new_commands?: Command[];
  new_escalations?: Escalation[];
  indoor_temp_c?: number;
  forecast_kw: number[] | null;
}
export interface LaneComparison {
  ts: string;
  saved_today_usd: number;
  peak_avoided_kw: number;
  month_peak_without_kw: number;
  month_peak_with_kw: number;
}
export type ProposalKind = "importance" | "peak_cap" | "authority" | "undo_decision" | "customer_event";
export interface Proposal {
  proposal_id: string;
  ts: string;
  kind: ProposalKind;
  payload: Record<string, unknown>;
  summary: string;
  status: "pending" | "confirmed" | "cancelled" | "expired";
  created_by: "ai";
  confirmed_via: "ui" | "asi_one" | null;
  expires_at: string;
}
export interface AgentLog {
  ts_real: string;
  from_agent: "concierge" | "weather" | "grid" | "events" | "claude" | "engine";
  to_agent: "concierge" | "weather" | "grid" | "events" | "claude" | "engine";
  kind: "request" | "response" | "post" | "error";
  summary: string;
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
  fixed_usd: number;
  total_usd: number;
  tariff_id: string;
}
export interface BacktestResult {
  dataset: string;
  month: string;
  policies: { without: Bill; timer: Bill; with: Bill };
  checks: { baseline_matches_raw: boolean; energy_conserved: boolean; rule_violations: number };
  assumptions_id: string;
  tariff_id: string;
  partial: boolean;
  saved_usd: number;
  saved_vs_timer_usd: number;
}
export interface PolicyCosts {
  without: number;
  timer: number;
  with: number;
}
/** One per replayed local day: the Proof chart's running line (CONTRACTS.md section 1 BacktestPoint). */
export interface BacktestPoint {
  dataset: string;
  assumptions_id: string;
  tariff_id: string;
  month: string;
  day: string;
  ts: string;
  partial: boolean;
  cost_to_date_usd: PolicyCosts;
  saved_month_to_date_usd: number;
  saved_vs_timer_month_to_date_usd: number;
  saved_year_to_date_usd: number;
}

// STUB: replace with generated REST/OpenAPI types.
export interface KitchenView {
  config: KitchenConfig;
  devices: Device[];
  tariff: Tariff;
}
export interface ImportanceUpdate {
  importance: Importance;
  limits: ImportanceLimits;
}
export interface PeakCapUpdate {
  peak_mode: "minimize" | "cap";
  peak_cap_kw: number | null;
}
export interface SimControlRequest {
  /** `next_day` only while `paused_reason` is `run_complete` (CONTRACTS.md §2 POST /api/sim/control). */
  action: "play" | "pause" | "reset" | "next_day";
  speed?: number;
}
export interface ClockState {
  playing: boolean;
  speed: number;
  sim_ts: string;
  tick_id: number;
  paused_reason: "manual" | "hub_waiting" | "sim_host_offline" | "run_complete" | null;
  day_index?: number;
  run_days?: number;
  phase?: "service" | "overnight" | "closed";
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
  months: string[];
  assumptions_id: string;
}
export interface Health {
  ok: boolean;
  kitchen_impl: "fake" | "real";
  live_transport: "spacetime" | "ws";
  store: "convex" | "memory";
  hardware: "off" | "sim_bridge" | "esp32";
  sim_host: "connected" | "offline";
}

// STUB: replace with generated WebSocket-schema types.
export type WarningCode = "cap_unreachable" | "sim_host_offline" | "hub_offline" | "live_transport_down" | "store_down";
export type WsMessage =
  | { type: "tick"; data: TickState }
  | { type: "decision"; data: Decision; explanation: string; explanation_source: "ai" | "template" }
  | ({ type: "clock" } & ClockState)
  | { type: "warning"; code: WarningCode; message: string; data: Record<string, unknown> }
  | { type: "chat_delta"; chat_id: string; text: string }
  | { type: "chat_done"; chat_id: string }
  | { type: "backtest_progress"; run_id: string; month: string; pct: number }
  | { type: "backtest_point"; run_id: string; data: BacktestPoint }
  | { type: "backtest_month"; run_id: string; data: BacktestResult }
  | { type: "comparison"; data: LaneComparison }
  | { type: "proposal"; data: Proposal }
  | { type: "escalation"; data: Escalation; explanation: string; explanation_source: "ai" | "template" }
  | { type: "context"; data: Context }
  | { type: "agent_log"; data: AgentLog };
export type WsMessageType = WsMessage["type"];

// SpacetimeDB rows as the app uses them (CONTRACTS.md section 5; snake_case, null for empty options). The generated
// bindings (`spacetime generate` -> src/module_bindings/, never hand-edited) are normalised into these in src/data/spacetime.ts.
export interface LiveTickRow {
  lane: Lane;
  ts: string;
  tick_id: number;
  total_kw: number;
  block_avg_kw: number;
  month_peak_kw: number;
  on_peak_month_peak_kw: number | null;
  peak_mode: "minimize" | "cap";
  peak_cap_kw: number | null;
  target_kw: number;
  energy_kwh_today: number;
  energy_kwh_month: number;
  price_usd_per_kwh_now: number;
  cost_usd_today: number;
  cost_usd_month: number;
  /** Meter.demand_peaks (DemandPeak[]) as a JSON string. */
  demand_peaks_json: string;
  customers_per_hour: number;
  indoor_temp_c: number;
  forecast_kw_json: string | null;
  forecast_ts: string | null;
}
export interface TickHistoryRow {
  lane: Lane;
  ts: string;
  total_kw: number;
  block_avg_kw: number;
}
export interface LiveDeviceRow {
  key: string;
  lane: Lane;
  device_id: string;
  type_id: string;
  name: string;
  importance: Importance;
  state: DeviceState;
  power_kw: number;
  rated_kw: number;
  power_pct: number;
  source: "simulated" | "measured";
  physical_json: string | null;
}
export interface LiveComparisonRow extends LaneComparison { id: 0 }
export interface LiveFeedRow {
  decision_id: string;
  lane: Lane;
  ts: string;
  device_id: string;
  action: CommandAction;
  value: number | null;
  status: DecisionStatus;
  reason_code: ReasonCode;
  effect_json: string;
  explanation: string;
  explanation_source: "ai" | "template";
}
export interface LiveClockRow extends ClockState { id: 0; sim_host: "connected" | "offline" }
export interface LiveContextRow {
  id: 0;
  weather_summary: string;
  weather_label: DataLabel;
  prices_summary: string;
  prices_label: DataLabel;
  events_summary: string;
  events_label: DataLabel;
  crowd_effect: "none" | "small" | "medium" | "large";
}
export interface LiveEscalationRow {
  escalation_id: string;
  lane: Lane;
  status: EscalationStatus;
  block_start: string;
  updated_ts: string;
  problem_json: string;
  options_json: string;
  default_option_id: string;
  active_option_id: string | null;
  deadline_sim_ts: string;
  chosen_option_id: string | null;
  resolved_by: Escalation["resolved_by"];
  rationale: string | null;
  claude_attempts_json: string;
  explanation: string;
  explanation_source: "ai" | "template";
}
export interface LiveAgentLogRow extends AgentLog { id: number }
export interface SurgeRequestRow {
  id: number;
  customers: number;
  duration_min: number;
  requested_by: string;
  created_at: string;
  consumed: boolean;
}
export interface BacktestPointRow {
  key: string; // "<run_id>:<day>"
  run_id: string;
  day: string;
  month: string;
  ts: string;
  partial: boolean;
  /** BacktestPoint.cost_to_date_usd (PolicyCosts) as a JSON string. */
  cost_to_date_json: string;
  saved_month_to_date_usd: number;
  saved_vs_timer_month_to_date_usd: number;
  saved_year_to_date_usd: number;
  dataset: string;
  tariff_id: string;
  assumptions_id: string;
}
export interface BacktestMonthRow {
  key: string; // "<run_id>:<month>"
  run_id: string;
  month: string;
  partial: boolean;
  saved_usd: number;
  saved_vs_timer_usd: number;
  /** BacktestResult.policies as a JSON string. */
  policies_json: string;
  /** BacktestResult.checks as a JSON string. */
  checks_json: string;
  dataset: string;
  tariff_id: string;
  assumptions_id: string;
}
export interface LiveTables {
  live_tick: LiveTickRow[];
  tick_history: TickHistoryRow[];
  live_device: LiveDeviceRow[];
  live_comparison: LiveComparisonRow[];
  live_feed: LiveFeedRow[];
  live_clock: LiveClockRow[];
  live_context: LiveContextRow[];
  live_escalation: LiveEscalationRow[];
  live_agent_log: LiveAgentLogRow[];
  surge_request: SurgeRequestRow[];
  backtest_point: BacktestPointRow[];
  backtest_month: BacktestMonthRow[];
}

// STUB: replace with generated hub-protocol types.
export interface HubHelloMessage {
  type: "hub_hello";
  protocol: 1;
  hub_id: "sim_hub";
  role: "sim_host";
  client: "wattwise-web/0.1";
}
export interface HubReportMessage { type: "hub_report"; tick_id: number; reports: Record<Lane, HubReport> }
export interface HubWelcomeMessage { type: "hub_welcome"; accepted: boolean; reason: "host_taken" | null; tick_id: number }
export interface SimBuildMessage {
  type: "sim_build";
  kitchen_id: string;
  config: KitchenConfig;
  catalog: EquipmentType[];
  devices: Device[];
  seed: number;
  start_sim_ts: string;
}
export interface Surge { surge_id: string; customers: number; duration_min: number }
export interface SimInputs { outdoor_temp_c?: number; crowd_multiplier?: number; is_open: boolean }
export interface SimTickMessage {
  type: "sim_tick";
  tick_id: number;
  sim_ts: string;
  minutes: number;
  surges: Surge[];
  inputs: SimInputs;
  commands: Command[];
  replay: boolean;
}
export interface SimControlMessage {
  type: "sim_control";
  action: "play" | "pause" | "reset";
  speed: number;
  paused_reason: ClockState["paused_reason"];
}
export type HubToServerMessage = HubHelloMessage | HubReportMessage;
export type ServerToHubMessage = HubWelcomeMessage | SimBuildMessage | SimTickMessage | SimControlMessage;
