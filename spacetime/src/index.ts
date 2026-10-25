// WattWise live shared kitchen: SpacetimeDB module (CONTRACTS.md section 5, docs/design/SPACETIMEDB.md).
//
// Mirror, don't decide: the engine computes every number; reducers only validate and write. No math on values, no
// randomness, no clock reads (ctx.timestamp only stamps surge requests and drives the prune schedule).
// State tables are written by the runtime identity alone (stored at `init`); viewers may only call `request_surge`.
// Every table is bounded (current state + short history); durable history lives in Convex.

import { schema, table, t, SenderError, ScheduleAt } from 'spacetimedb/server';
import type { InferSchema, ReducerCtx } from 'spacetimedb/server';

// ---------------------------------------------------------------------------------------------------------------------
// Bounds (SPACETIMEDB.md principle 4)
// ---------------------------------------------------------------------------------------------------------------------
const TICK_HISTORY_SIM_MIN = 180; // per lane
const FEED_MAX = 50;
const ESCALATION_MAX = 20;
const AGENT_LOG_MAX = 300;
const BACKTEST_POINT_MAX = 366;
const BACKTEST_MONTH_MAX = 12;
const SURGE_MAX = 200; // request table: consumed rows beyond this are dropped oldest first
const PRUNE_EVERY_MICROS = 60_000_000n; // scheduled safety net; publish reducers already bound on write

const LANES = new Set(['without', 'with']);

// ---------------------------------------------------------------------------------------------------------------------
// Tables
// ---------------------------------------------------------------------------------------------------------------------
const runtime_config = table(
  { name: 'runtime_config' }, // private: only the module reads it
  {
    id: t.u32().primaryKey(),
    runtime_identity: t.identity(),
  }
);

const live_tick = table(
  { name: 'live_tick', public: true },
  {
    lane: t.string().primaryKey(),
    ts: t.string(),
    tick_id: t.u32(),
    total_kw: t.f64(),
    block_avg_kw: t.f64(),
    month_peak_kw: t.f64(),
    on_peak_month_peak_kw: t.option(t.f64()),
    peak_mode: t.string(),
    peak_cap_kw: t.option(t.f64()),
    target_kw: t.f64(),
    energy_kwh_today: t.f64(),
    energy_kwh_month: t.f64(),
    price_usd_per_kwh_now: t.f64(),
    cost_usd_today: t.f64(),
    cost_usd_month: t.f64(),
    demand_peaks_json: t.string(),
    customers_per_hour: t.u32(),
    indoor_temp_c: t.f64(),
    forecast_kw_json: t.option(t.string()),
    forecast_ts: t.option(t.string()),
  }
);

// Key lane + ts (CONTRACTS.md): stored as one string primary key "<lane>:<ts>" so upserts are a single find.
const tick_history = table(
  { name: 'tick_history', public: true },
  {
    key: t.string().primaryKey(),
    lane: t.string().index('btree'),
    ts: t.string(),
    total_kw: t.f64(),
    block_avg_kw: t.f64(),
  }
);

const live_device = table(
  { name: 'live_device', public: true },
  {
    key: t.string().primaryKey(), // "<lane>:<device_id>"
    lane: t.string(),
    device_id: t.string(),
    type_id: t.string(),
    name: t.string(),
    importance: t.string(),
    state: t.string(),
    power_kw: t.f64(),
    rated_kw: t.f64(),
    power_pct: t.u32(),
    source: t.string(),
    physical_json: t.option(t.string()),
  }
);

const live_comparison = table(
  { name: 'live_comparison', public: true },
  {
    id: t.u32().primaryKey(), // single row, id = 0
    ts: t.string(),
    saved_today_usd: t.f64(),
    peak_avoided_kw: t.f64(),
    month_peak_without_kw: t.f64(),
    month_peak_with_kw: t.f64(),
  }
);

const live_feed = table(
  { name: 'live_feed', public: true },
  {
    decision_id: t.string().primaryKey(),
    lane: t.string(),
    ts: t.string(),
    device_id: t.string(),
    action: t.string(),
    value: t.option(t.i32()),
    status: t.string(),
    reason_code: t.string(),
    effect_json: t.string(),
    explanation: t.string(),
    explanation_source: t.string(),
  }
);

const live_clock = table(
  { name: 'live_clock', public: true },
  {
    id: t.u32().primaryKey(), // single row, id = 0
    playing: t.bool(),
    speed: t.u32(),
    sim_ts: t.string(),
    tick_id: t.u32(),
    paused_reason: t.option(t.string()),
    day_index: t.u32(),
    run_days: t.u32(),
    phase: t.string(),
    sim_host: t.string(),
  }
);

const live_context = table(
  { name: 'live_context', public: true },
  {
    id: t.u32().primaryKey(), // single row, id = 0
    weather_summary: t.string(),
    weather_label: t.string(),
    prices_summary: t.string(),
    prices_label: t.string(),
    events_summary: t.string(),
    events_label: t.string(),
    crowd_effect: t.string(),
  }
);

const live_escalation = table(
  { name: 'live_escalation', public: true },
  {
    escalation_id: t.string().primaryKey(),
    lane: t.string(),
    status: t.string(),
    block_start: t.string(),
    updated_ts: t.string(),
    problem_json: t.string(),
    options_json: t.string(),
    default_option_id: t.string(),
    active_option_id: t.option(t.string()),
    deadline_sim_ts: t.string(),
    chosen_option_id: t.option(t.string()),
    resolved_by: t.option(t.string()),
    rationale: t.option(t.string()),
  }
);

const live_agent_log = table(
  { name: 'live_agent_log', public: true },
  {
    id: t.u32().primaryKey().autoInc(),
    ts_real: t.string(),
    from_agent: t.string(),
    to_agent: t.string(),
    kind: t.string(),
    summary: t.string(),
  }
);

const backtest_point = table(
  { name: 'backtest_point', public: true },
  {
    key: t.string().primaryKey(), // "<run_id>:<day>"
    run_id: t.string(),
    day: t.string(),
    month: t.string(),
    ts: t.string(),
    partial: t.bool(),
    cost_to_date_json: t.string(),
    saved_month_to_date_usd: t.f64(),
    saved_vs_timer_month_to_date_usd: t.f64(),
    saved_year_to_date_usd: t.f64(),
    dataset: t.string(),
    tariff_id: t.string(),
    assumptions_id: t.string(),
  }
);

const backtest_month = table(
  { name: 'backtest_month', public: true },
  {
    key: t.string().primaryKey(), // "<run_id>:<month>"
    run_id: t.string(),
    month: t.string(),
    partial: t.bool(),
    saved_usd: t.f64(),
    saved_vs_timer_usd: t.f64(),
    policies_json: t.string(),
    checks_json: t.string(),
    dataset: t.string(),
    tariff_id: t.string(),
    assumptions_id: t.string(),
  }
);

const surge_request = table(
  { name: 'surge_request', public: true },
  {
    id: t.u32().primaryKey().autoInc(),
    customers: t.u32(),
    duration_min: t.u32(),
    requested_by: t.string(), // caller identity, hex
    created_at: t.string(), // ISO UTC, from ctx.timestamp
    consumed: t.bool(),
  }
);

const prune_schedule = table(
  { name: 'prune_schedule' },
  {
    scheduled_id: t.u64().primaryKey().autoInc(),
    scheduled_at: t.scheduleAt(),
  }
);

const spacetimedb = schema({
  runtime_config,
  live_tick,
  tick_history,
  live_device,
  live_comparison,
  live_feed,
  live_clock,
  live_context,
  live_escalation,
  live_agent_log,
  backtest_point,
  backtest_month,
  surge_request,
  prune_schedule,
});
export default spacetimedb;

type Ctx = ReducerCtx<InferSchema<typeof spacetimedb>>;
type LiveTickRow = Parameters<Ctx['db']['live_tick']['insert']>[0];

// ---------------------------------------------------------------------------------------------------------------------
// Validation helpers (validate and write; never compute)
// ---------------------------------------------------------------------------------------------------------------------
type Json = Record<string, unknown>;

function parseObject(raw: string, what: string): Json {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    throw new SenderError(`${what}: not valid JSON`);
  }
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new SenderError(`${what}: expected a JSON object`);
  }
  return value as Json;
}

function str(o: Json, k: string, what: string): string {
  const v = o[k];
  if (typeof v !== 'string') throw new SenderError(`${what}.${k}: expected a string`);
  return v;
}

function optStr(o: Json, k: string, what: string): string | undefined {
  const v = o[k];
  if (v === null || v === undefined) return undefined;
  if (typeof v !== 'string') throw new SenderError(`${what}.${k}: expected a string or null`);
  return v;
}

function num(o: Json, k: string, what: string): number {
  const v = o[k];
  if (typeof v !== 'number' || !Number.isFinite(v)) throw new SenderError(`${what}.${k}: expected a number`);
  return v;
}

function optNum(o: Json, k: string, what: string): number | undefined {
  const v = o[k];
  if (v === null || v === undefined) return undefined;
  if (typeof v !== 'number' || !Number.isFinite(v)) throw new SenderError(`${what}.${k}: expected a number or null`);
  return v;
}

function uint(o: Json, k: string, what: string): number {
  const v = num(o, k, what);
  if (!Number.isInteger(v) || v < 0) throw new SenderError(`${what}.${k}: expected a non-negative integer`);
  return v;
}

function optInt(o: Json, k: string, what: string): number | undefined {
  const v = optNum(o, k, what);
  if (v !== undefined && !Number.isInteger(v)) throw new SenderError(`${what}.${k}: expected an integer or null`);
  return v;
}

function bool(o: Json, k: string, what: string): boolean {
  const v = o[k];
  if (typeof v !== 'boolean') throw new SenderError(`${what}.${k}: expected a boolean`);
  return v;
}

/** A `*_json` column: must be valid JSON (or null when optional). Stored as given. */
function jsonCol(o: Json, k: string, what: string): string {
  const v = str(o, k, what);
  try {
    JSON.parse(v);
  } catch {
    throw new SenderError(`${what}.${k}: not valid JSON`);
  }
  return v;
}

function optJsonCol(o: Json, k: string, what: string): string | undefined {
  const v = optStr(o, k, what);
  if (v === undefined) return undefined;
  try {
    JSON.parse(v);
  } catch {
    throw new SenderError(`${what}.${k}: not valid JSON`);
  }
  return v;
}

function lane(o: Json, what: string): string {
  const v = str(o, 'lane', what);
  if (!LANES.has(v)) throw new SenderError(`${what}.lane: expected "without" or "with"`);
  return v;
}

/** Numeric suffix of an id like d_0041 / e_10000 (zero-padded ids widen past 9999, so string order is not enough). */
function idNumber(id: string): number {
  const m = /_(\d+)$/.exec(id);
  return m ? Number(m[1]) : 0;
}

function requireRuntime(ctx: Ctx): void {
  const cfg = ctx.db.runtime_config.id.find(0);
  if (!cfg || !cfg.runtime_identity.isEqual(ctx.sender)) {
    throw new SenderError('runtime identity only');
  }
}

// ---------------------------------------------------------------------------------------------------------------------
// Bounding (deterministic; called on write and by the scheduled prune)
// ---------------------------------------------------------------------------------------------------------------------
function boundTickHistory(ctx: Ctx, laneName: string): void {
  const rows = [...ctx.db.tick_history.lane.filter(laneName)];
  if (rows.length === 0) return;
  let latest = rows[0].ts;
  for (const r of rows) if (r.ts > latest) latest = r.ts; // ISO UTC strings of one format sort in time order
  const cutoffMs = Date.parse(latest) - TICK_HISTORY_SIM_MIN * 60_000;
  for (const r of rows) {
    if (Date.parse(r.ts) <= cutoffMs) ctx.db.tick_history.delete(r);
  }
}

function boundById<R>(rows: R[], max: number, order: (r: R) => number, drop: (r: R) => void): void {
  if (rows.length <= max) return;
  const sorted = [...rows].sort((a, b) => order(a) - order(b));
  for (const r of sorted.slice(0, sorted.length - max)) drop(r);
}

function boundFeed(ctx: Ctx): void {
  boundById([...ctx.db.live_feed.iter()], FEED_MAX, r => idNumber(r.decision_id), r => ctx.db.live_feed.delete(r));
}

function boundEscalations(ctx: Ctx): void {
  boundById([...ctx.db.live_escalation.iter()], ESCALATION_MAX, r => idNumber(r.escalation_id), r =>
    ctx.db.live_escalation.delete(r)
  );
}

function boundAgentLog(ctx: Ctx): void {
  boundById([...ctx.db.live_agent_log.iter()], AGENT_LOG_MAX, r => r.id, r => ctx.db.live_agent_log.delete(r));
}

function boundBacktest(ctx: Ctx): void {
  const points = [...ctx.db.backtest_point.iter()].sort((a, b) => (a.day < b.day ? -1 : a.day > b.day ? 1 : 0));
  for (const r of points.slice(0, Math.max(0, points.length - BACKTEST_POINT_MAX))) ctx.db.backtest_point.delete(r);
  const months = [...ctx.db.backtest_month.iter()].sort((a, b) => (a.month < b.month ? -1 : a.month > b.month ? 1 : 0));
  for (const r of months.slice(0, Math.max(0, months.length - BACKTEST_MONTH_MAX))) ctx.db.backtest_month.delete(r);
}

function boundSurges(ctx: Ctx): void {
  const consumed = [...ctx.db.surge_request.iter()].filter(r => r.consumed);
  const total = Number(ctx.db.surge_request.count());
  if (total <= SURGE_MAX) return;
  consumed.sort((a, b) => a.id - b.id);
  for (const r of consumed.slice(0, total - SURGE_MAX)) ctx.db.surge_request.delete(r);
}

/** Latest backtest run only: drop every row of another run. */
function keepOnlyRun(ctx: Ctx, runId: string): void {
  for (const r of [...ctx.db.backtest_point.iter()]) if (r.run_id !== runId) ctx.db.backtest_point.delete(r);
  for (const r of [...ctx.db.backtest_month.iter()]) if (r.run_id !== runId) ctx.db.backtest_month.delete(r);
}

// upsert by primary key
function upsertTick(ctx: Ctx, row: LiveTickRow): void {
  if (ctx.db.live_tick.lane.find(row.lane)) ctx.db.live_tick.lane.update(row);
  else ctx.db.live_tick.insert(row);
}

// ---------------------------------------------------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------------------------------------------------
export const init = spacetimedb.init(ctx => {
  // The publisher's identity is the runtime identity (the backend calls reducers with that identity's token).
  ctx.db.runtime_config.insert({ id: 0, runtime_identity: ctx.sender });
  ctx.db.prune_schedule.insert({ scheduled_id: 0n, scheduled_at: ScheduleAt.interval(PRUNE_EVERY_MICROS) });
});

export const prune = spacetimedb.reducer(
  { name: 'prune', onSchedule: prune_schedule },
  { arg: prune_schedule.rowType },
  ctx => {
    // Scheduled calls come from the module itself; anyone else is refused.
    if (!ctx.sender.isEqual(ctx.databaseIdentity)) throw new SenderError('prune is scheduled only');
    for (const l of LANES) boundTickHistory(ctx, l);
    boundFeed(ctx);
    boundEscalations(ctx);
    boundAgentLog(ctx);
    boundBacktest(ctx);
    boundSurges(ctx);
  }
);

// ---------------------------------------------------------------------------------------------------------------------
// Runtime reducers
// ---------------------------------------------------------------------------------------------------------------------
export const publish_ticks = spacetimedb.reducer({ payload_json: t.string() }, (ctx, { payload_json }) => {
  requireRuntime(ctx);
  const p = parseObject(payload_json, 'publish_ticks');
  const ticks = p['live_tick'];
  const history = p['tick_history'];
  const devices = p['live_device'];
  const cmp = p['live_comparison'];
  if (!Array.isArray(ticks) || ticks.length !== 2) throw new SenderError('publish_ticks.live_tick: expected 2 rows');
  if (!Array.isArray(history) || history.length !== 2) throw new SenderError('publish_ticks.tick_history: expected 2 rows');
  if (!Array.isArray(devices)) throw new SenderError('publish_ticks.live_device: expected an array');
  if (cmp === null || typeof cmp !== 'object' || Array.isArray(cmp)) {
    throw new SenderError('publish_ticks.live_comparison: expected an object');
  }

  for (const raw of ticks) {
    const o = raw as Json;
    const w = 'live_tick';
    upsertTick(ctx, {
      lane: lane(o, w),
      ts: str(o, 'ts', w),
      tick_id: uint(o, 'tick_id', w),
      total_kw: num(o, 'total_kw', w),
      block_avg_kw: num(o, 'block_avg_kw', w),
      month_peak_kw: num(o, 'month_peak_kw', w),
      on_peak_month_peak_kw: optNum(o, 'on_peak_month_peak_kw', w),
      peak_mode: str(o, 'peak_mode', w),
      peak_cap_kw: optNum(o, 'peak_cap_kw', w),
      target_kw: num(o, 'target_kw', w),
      energy_kwh_today: num(o, 'energy_kwh_today', w),
      energy_kwh_month: num(o, 'energy_kwh_month', w),
      price_usd_per_kwh_now: num(o, 'price_usd_per_kwh_now', w),
      cost_usd_today: num(o, 'cost_usd_today', w),
      cost_usd_month: num(o, 'cost_usd_month', w),
      demand_peaks_json: jsonCol(o, 'demand_peaks_json', w),
      customers_per_hour: uint(o, 'customers_per_hour', w),
      indoor_temp_c: num(o, 'indoor_temp_c', w),
      forecast_kw_json: optJsonCol(o, 'forecast_kw_json', w),
      forecast_ts: optStr(o, 'forecast_ts', w),
    });
  }

  const lanesSeen = new Set<string>();
  for (const raw of history) {
    const o = raw as Json;
    const w = 'tick_history';
    const l = lane(o, w);
    const ts = str(o, 'ts', w);
    const row = { key: `${l}:${ts}`, lane: l, ts, total_kw: num(o, 'total_kw', w), block_avg_kw: num(o, 'block_avg_kw', w) };
    if (ctx.db.tick_history.key.find(row.key)) ctx.db.tick_history.key.update(row);
    else ctx.db.tick_history.insert(row);
    lanesSeen.add(l);
  }
  for (const l of lanesSeen) boundTickHistory(ctx, l);

  for (const raw of devices) {
    const o = raw as Json;
    const w = 'live_device';
    const l = lane(o, w);
    const deviceId = str(o, 'device_id', w);
    const key = str(o, 'key', w);
    if (key !== `${l}:${deviceId}`) throw new SenderError('live_device.key: expected "<lane>:<device_id>"');
    const row = {
      key,
      lane: l,
      device_id: deviceId,
      type_id: str(o, 'type_id', w),
      name: str(o, 'name', w),
      importance: str(o, 'importance', w),
      state: str(o, 'state', w),
      power_kw: num(o, 'power_kw', w),
      rated_kw: num(o, 'rated_kw', w),
      power_pct: uint(o, 'power_pct', w),
      source: str(o, 'source', w),
      physical_json: optJsonCol(o, 'physical_json', w),
    };
    if (ctx.db.live_device.key.find(key)) ctx.db.live_device.key.update(row);
    else ctx.db.live_device.insert(row);
  }

  const c = cmp as Json;
  const w = 'live_comparison';
  const crow = {
    id: 0,
    ts: str(c, 'ts', w),
    saved_today_usd: num(c, 'saved_today_usd', w),
    peak_avoided_kw: num(c, 'peak_avoided_kw', w),
    month_peak_without_kw: num(c, 'month_peak_without_kw', w),
    month_peak_with_kw: num(c, 'month_peak_with_kw', w),
  };
  if (ctx.db.live_comparison.id.find(0)) ctx.db.live_comparison.id.update(crow);
  else ctx.db.live_comparison.insert(crow);
});

export const publish_feed = spacetimedb.reducer({ decision_json: t.string() }, (ctx, { decision_json }) => {
  requireRuntime(ctx);
  const w = 'publish_feed';
  const o = parseObject(decision_json, w);
  const source = str(o, 'explanation_source', w);
  if (source !== 'ai' && source !== 'template') throw new SenderError(`${w}.explanation_source: ai | template`);
  const row = {
    decision_id: str(o, 'decision_id', w),
    lane: lane(o, w),
    ts: str(o, 'ts', w),
    device_id: str(o, 'device_id', w),
    action: str(o, 'action', w),
    value: optInt(o, 'value', w),
    status: str(o, 'status', w),
    reason_code: str(o, 'reason_code', w),
    effect_json: jsonCol(o, 'effect_json', w),
    explanation: str(o, 'explanation', w),
    explanation_source: source,
  };
  if (ctx.db.live_feed.decision_id.find(row.decision_id)) ctx.db.live_feed.decision_id.update(row);
  else ctx.db.live_feed.insert(row);
  boundFeed(ctx);
});

export const set_clock = spacetimedb.reducer(
  {
    playing: t.bool(),
    speed: t.u32(),
    sim_ts: t.string(),
    tick_id: t.u32(),
    paused_reason: t.option(t.string()),
    day_index: t.u32(),
    run_days: t.u32(),
    phase: t.string(),
    sim_host: t.string(),
  },
  (ctx, args) => {
    requireRuntime(ctx);
    if (args.sim_host !== 'connected' && args.sim_host !== 'offline') {
      throw new SenderError('set_clock.sim_host: connected | offline');
    }
    if (args.day_index < 1 || args.day_index > args.run_days) throw new SenderError('set_clock: 1 <= day_index <= run_days');
    const row = { id: 0, ...args, paused_reason: args.paused_reason };
    if (ctx.db.live_clock.id.find(0)) ctx.db.live_clock.id.update(row);
    else ctx.db.live_clock.insert(row);
  }
);

export const publish_context = spacetimedb.reducer({ context_json: t.string() }, (ctx, { context_json }) => {
  requireRuntime(ctx);
  const w = 'publish_context';
  const o = parseObject(context_json, w);
  const row = {
    id: 0,
    weather_summary: str(o, 'weather_summary', w),
    weather_label: str(o, 'weather_label', w),
    prices_summary: str(o, 'prices_summary', w),
    prices_label: str(o, 'prices_label', w),
    events_summary: str(o, 'events_summary', w),
    events_label: str(o, 'events_label', w),
    crowd_effect: str(o, 'crowd_effect', w),
  };
  if (ctx.db.live_context.id.find(0)) ctx.db.live_context.id.update(row);
  else ctx.db.live_context.insert(row);
});

export const publish_escalation = spacetimedb.reducer({ escalation_json: t.string() }, (ctx, { escalation_json }) => {
  requireRuntime(ctx);
  const w = 'publish_escalation';
  const o = parseObject(escalation_json, w);
  const row = {
    escalation_id: str(o, 'escalation_id', w),
    lane: lane(o, w),
    status: str(o, 'status', w),
    block_start: str(o, 'block_start', w),
    updated_ts: str(o, 'updated_ts', w),
    problem_json: jsonCol(o, 'problem_json', w),
    options_json: jsonCol(o, 'options_json', w),
    default_option_id: str(o, 'default_option_id', w),
    active_option_id: optStr(o, 'active_option_id', w),
    deadline_sim_ts: str(o, 'deadline_sim_ts', w),
    chosen_option_id: optStr(o, 'chosen_option_id', w),
    resolved_by: optStr(o, 'resolved_by', w),
    rationale: optStr(o, 'rationale', w),
  };
  if (ctx.db.live_escalation.escalation_id.find(row.escalation_id)) ctx.db.live_escalation.escalation_id.update(row);
  else ctx.db.live_escalation.insert(row);
  boundEscalations(ctx);
});

export const log_agent = spacetimedb.reducer({ agent_log_json: t.string() }, (ctx, { agent_log_json }) => {
  requireRuntime(ctx);
  const w = 'log_agent';
  const o = parseObject(agent_log_json, w);
  ctx.db.live_agent_log.insert({
    id: 0, // auto-inc
    ts_real: str(o, 'ts_real', w),
    from_agent: str(o, 'from_agent', w),
    to_agent: str(o, 'to_agent', w),
    kind: str(o, 'kind', w),
    summary: str(o, 'summary', w),
  });
  boundAgentLog(ctx);
});

export const publish_backtest_point = spacetimedb.reducer({ point_json: t.string() }, (ctx, { point_json }) => {
  requireRuntime(ctx);
  const w = 'publish_backtest_point';
  const o = parseObject(point_json, w);
  const runId = str(o, 'run_id', w);
  const day = str(o, 'day', w);
  const month = str(o, 'month', w);
  const key = str(o, 'key', w);
  if (key !== `${runId}:${day}`) throw new SenderError(`${w}.key: expected "<run_id>:<day>"`);
  if (!day.startsWith(`${month}-`)) throw new SenderError(`${w}: day is not in month`);
  const row = {
    key,
    run_id: runId,
    day,
    month,
    ts: str(o, 'ts', w),
    partial: bool(o, 'partial', w),
    cost_to_date_json: jsonCol(o, 'cost_to_date_json', w),
    saved_month_to_date_usd: num(o, 'saved_month_to_date_usd', w),
    saved_vs_timer_month_to_date_usd: num(o, 'saved_vs_timer_month_to_date_usd', w),
    saved_year_to_date_usd: num(o, 'saved_year_to_date_usd', w),
    dataset: str(o, 'dataset', w),
    tariff_id: str(o, 'tariff_id', w),
    assumptions_id: str(o, 'assumptions_id', w),
  };
  keepOnlyRun(ctx, runId);
  if (ctx.db.backtest_point.key.find(key)) ctx.db.backtest_point.key.update(row);
  else ctx.db.backtest_point.insert(row);
  boundBacktest(ctx);
});

export const publish_backtest_month = spacetimedb.reducer({ month_json: t.string() }, (ctx, { month_json }) => {
  requireRuntime(ctx);
  const w = 'publish_backtest_month';
  const o = parseObject(month_json, w);
  const runId = str(o, 'run_id', w);
  const month = str(o, 'month', w);
  const key = str(o, 'key', w);
  if (key !== `${runId}:${month}`) throw new SenderError(`${w}.key: expected "<run_id>:<month>"`);
  const row = {
    key,
    run_id: runId,
    month,
    partial: bool(o, 'partial', w),
    saved_usd: num(o, 'saved_usd', w),
    saved_vs_timer_usd: num(o, 'saved_vs_timer_usd', w),
    policies_json: jsonCol(o, 'policies_json', w),
    checks_json: jsonCol(o, 'checks_json', w),
    dataset: str(o, 'dataset', w),
    tariff_id: str(o, 'tariff_id', w),
    assumptions_id: str(o, 'assumptions_id', w),
  };
  keepOnlyRun(ctx, runId);
  if (ctx.db.backtest_month.key.find(key)) ctx.db.backtest_month.key.update(row);
  else ctx.db.backtest_month.insert(row);
  boundBacktest(ctx);
});

export const reset_backtest = spacetimedb.reducer({ run_id: t.string() }, (ctx, { run_id }) => {
  requireRuntime(ctx);
  // A new run starts: clear the previous run's rows (every row of another run id, and any partial rows of this id).
  ctx.db.backtest_point.clear();
  ctx.db.backtest_month.clear();
  void run_id;
});

export const reset_all = spacetimedb.reducer(ctx => {
  requireRuntime(ctx);
  // New kitchen: clear every live table (the month-to-date store in live_tick goes with it). Backtest rows and surge
  // requests are not live kitchen state and stay.
  ctx.db.live_tick.clear();
  ctx.db.tick_history.clear();
  ctx.db.live_device.clear();
  ctx.db.live_comparison.clear();
  ctx.db.live_feed.clear();
  ctx.db.live_clock.clear();
  ctx.db.live_context.clear();
  ctx.db.live_escalation.clear();
  ctx.db.live_agent_log.clear();
});

export const consume_surge = spacetimedb.reducer({ id: t.u32() }, (ctx, { id }) => {
  requireRuntime(ctx);
  const row = ctx.db.surge_request.id.find(id);
  if (!row) throw new SenderError(`consume_surge: no surge_request ${id}`);
  if (!row.consumed) ctx.db.surge_request.id.update({ ...row, consumed: true });
  boundSurges(ctx);
});

// ---------------------------------------------------------------------------------------------------------------------
// Public request reducer (anyone: judges' phones, every viewer)
// ---------------------------------------------------------------------------------------------------------------------
export const request_surge = spacetimedb.reducer(
  { customers: t.u32(), duration_min: t.u32() },
  (ctx, { customers, duration_min }) => {
    if (customers < 1 || customers > 80) throw new SenderError('request_surge.customers: 1 to 80');
    if (duration_min < 15 || duration_min > 120) throw new SenderError('request_surge.duration_min: 15 to 120');
    ctx.db.surge_request.insert({
      id: 0, // auto-inc
      customers,
      duration_min,
      requested_by: ctx.sender.toHexString(),
      created_at: ctx.timestamp.toISOString(),
      consumed: false,
    });
    boundSurges(ctx);
  }
);
