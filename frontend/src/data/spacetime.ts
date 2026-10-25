import type {
  Escalation,
  LiveAgentLogRow,
  LiveClockRow,
  LiveComparisonRow,
  LiveDeviceRow,
  LiveEscalationRow,
  LiveFeedRow,
  LiveTables,
  LiveTickRow,
  TickState,
  WsMessage,
} from "@/types";

// SpacetimeDB live source (CONTRACTS.md section 5). The runtime publishes the shared kitchen into tables; every viewer
// subscribes, so a judge's phone and the projector see the same kitchen. Table rows go straight into the typed row store
// (useLive); they are also converted into the messages `/ws` sends so the legacy screen store keeps working.

const parse = <T,>(json: string | null | undefined, fallback: T): T => {
  if (!json) return fallback;
  try {
    return JSON.parse(json) as T;
  } catch {
    return fallback;
  }
};

/**
 * live_tick + that lane's live_device rows → a `tick` message. Fields live_tick doesn't carry (block start) are left at
 * what's knowable, never computed here.
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
      on_peak_month_peak_kw: tick.on_peak_month_peak_kw,
      peak_mode: tick.peak_mode,
      peak_cap_kw: tick.peak_cap_kw,
      target_kw: tick.target_kw,
      energy_kwh_today: tick.energy_kwh_today,
      energy_kwh_month: tick.energy_kwh_month,
      price_usd_per_kwh_now: tick.price_usd_per_kwh_now,
      cost_usd_today: tick.cost_usd_today,
      cost_usd_month: tick.cost_usd_month,
      demand_peaks: parse(tick.demand_peaks_json, []),
    },
    customers_per_hour: tick.customers_per_hour,
    new_decisions: [],
    indoor_temp_c: tick.indoor_temp_c,
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
      ts: prev?.ts ?? row.updated_ts,
      block_start: row.block_start,
      problem,
      options: parse(row.options_json, prev?.options ?? []),
      default_option_id: row.default_option_id,
      active_option_id: row.active_option_id,
      updated_ts: row.updated_ts,
      deadline_sim_ts: row.deadline_sim_ts,
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
  token?: string;
}

// ---------------------------------------------------------------------------------------------------------------------
// Generated bindings (src/module_bindings/, written by `npm run generate` in spacetime/; never hand-edited).
// Loaded through import.meta.glob so the app builds before they exist (then SpacetimeDB is "unavailable" and /ws is used).
// The structural types below are the minimum this file uses from them.
// ---------------------------------------------------------------------------------------------------------------------
type BindingRow = Record<string, unknown>;
interface BindingTable {
  iter(): Iterable<BindingRow>;
  onInsert(cb: (ctx: unknown, row: BindingRow) => void): void;
  onUpdate?(cb: (ctx: unknown, oldRow: BindingRow, newRow: BindingRow) => void): void;
  onDelete(cb: (ctx: unknown, row: BindingRow) => void): void;
}
interface BindingConnection {
  db: Record<string, BindingTable | undefined>;
  reducers: Record<string, ((args: Record<string, unknown>) => unknown) | undefined>;
  subscriptionBuilder(): {
    onApplied(cb: () => void): ReturnType<BindingConnection["subscriptionBuilder"]>;
    onError(cb: (...args: unknown[]) => void): ReturnType<BindingConnection["subscriptionBuilder"]>;
    subscribe(queries: string[]): unknown;
  };
  disconnect(): void;
}
interface BindingBuilder {
  withUri(uri: string): BindingBuilder;
  withDatabaseName(name: string): BindingBuilder;
  withToken(token?: string): BindingBuilder;
  onConnect(cb: (conn: BindingConnection, identity: unknown, token: string) => void): BindingBuilder;
  onConnectError(cb: (ctx: unknown, err: Error) => void): BindingBuilder;
  onDisconnect(cb: (...args: unknown[]) => void): BindingBuilder;
  build(): BindingConnection;
}
interface BindingsModule {
  DbConnection: { builder(): BindingBuilder };
}

const bindingModules = import.meta.glob("../module_bindings/index.ts");

async function loadBindings(): Promise<BindingsModule> {
  const load = Object.values(bindingModules)[0];
  if (!load) throw new SpacetimeUnavailable("SpacetimeDB bindings are not generated yet (run `npm run generate` in spacetime/)");
  return (await load()) as BindingsModule;
}

export const LIVE_TABLES = [
  "live_tick",
  "tick_history",
  "live_device",
  "live_comparison",
  "live_feed",
  "live_clock",
  "live_context",
  "live_escalation",
  "live_agent_log",
  "surge_request",
  "backtest_point",
  "backtest_month",
] as const satisfies readonly (keyof LiveTables)[];

const camel = (s: string) => s.replace(/_([a-z0-9])/g, (_, c: string) => c.toUpperCase());
const snake = (s: string) => s.replace(/[A-Z]/g, (c) => `_${c.toLowerCase()}`);

/** Generated binding row → section 5 row: snake_case keys, options undefined → null, bigint ids → number. */
export function normaliseRow(row: BindingRow): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(row)) {
    out[snake(k)] = v === undefined ? null : typeof v === "bigint" ? Number(v) : v;
  }
  return out;
}

const tableOf = (conn: BindingConnection, name: string): BindingTable | undefined => conn.db[name] ?? conn.db[camel(name)];

function snapshotTables(conn: BindingConnection): LiveTables {
  const out = {} as Record<string, unknown[]>;
  for (const name of LIVE_TABLES) {
    const table = tableOf(conn, name);
    out[name] = table ? [...table.iter()].map(normaliseRow) : [];
  }
  out.tick_history = (out.tick_history as Record<string, unknown>[])
    .map(({ key: _key, ...row }) => row)
    .sort((a, b) => String(a.ts).localeCompare(String(b.ts)));
  return out as unknown as LiveTables;
}

/** Legacy screen-store messages for one changed row (ticks rebuild from the whole snapshot). */
function messagesFor(name: string, tables: LiveTables, row: Record<string, unknown>): WsMessage[] {
  switch (name) {
    case "live_tick":
      return [tickMessage(row as unknown as LiveTickRow, tables.live_device)];
    case "live_comparison":
      return [comparisonMessage(row as unknown as LiveComparisonRow)];
    case "live_feed":
      return [feedMessage(row as unknown as LiveFeedRow)];
    case "live_clock":
      return [clockMessage(row as unknown as LiveClockRow)];
    case "live_escalation":
      return [escalationMessage(row as unknown as LiveEscalationRow)];
    case "live_agent_log":
      return [agentLogMessage(row as unknown as LiveAgentLogRow)];
    default:
      return [];
  }
}

let activeConnection: BindingConnection | null = null;

/**
 * Subscribe to every section 5 table. `onTables` gets a full snapshot of the rows after each change (throttled by the
 * caller); `onMessages` gets legacy messages for changed rows. Returns a stop function. Throws SpacetimeUnavailable when
 * the bindings are missing or the connection fails, so the caller stays on /ws.
 */
export async function connectSpacetime(
  config: SpacetimeConfig,
  onTables: (tables: LiveTables) => void,
  onMessages: (msgs: WsMessage[]) => void,
  onStatus: (status: "connecting" | "open" | "closed") => void,
): Promise<() => void> {
  const { DbConnection } = await loadBindings();
  onStatus("connecting");
  const conn = await new Promise<BindingConnection>((resolve, reject) => {
    DbConnection.builder()
      .withUri(config.uri)
      .withDatabaseName(config.database)
      .withToken(config.token)
      .onConnect((c) => resolve(c))
      .onConnectError((_ctx, err) => reject(new SpacetimeUnavailable(String(err))))
      .onDisconnect(() => onStatus("closed"))
      .build();
  });
  // One reducer call changes many rows (publish_ticks: ~30); coalesce them into one snapshot per task.
  let pending: [string, Record<string, unknown>][] = [];
  let scheduled = false;
  const flush = () => {
    scheduled = false;
    const tables = snapshotTables(conn);
    onTables(tables);
    const changed = pending;
    pending = [];
    onMessages(changed.flatMap(([name, row]) => messagesFor(name, tables, row)));
  };
  const schedule = (name: string, row: BindingRow | null) => {
    if (row && name !== "live_device" && name !== "tick_history") pending.push([name, normaliseRow(row)]);
    if (!scheduled) {
      scheduled = true;
      setTimeout(flush, 0);
    }
  };
  for (const name of LIVE_TABLES) {
    const table = tableOf(conn, name);
    if (!table) continue;
    table.onInsert((_ctx, row) => schedule(name, row));
    table.onUpdate?.((_ctx, _old, row) => schedule(name, row));
    table.onDelete(() => schedule(name, null));
  }
  await new Promise<void>((resolve, reject) => {
    conn
      .subscriptionBuilder()
      .onApplied(() => resolve())
      .onError((...err) => reject(new SpacetimeUnavailable(String(err[err.length - 1]))))
      .subscribe(LIVE_TABLES.map((t) => `SELECT * FROM ${t}`));
  });
  activeConnection = conn;
  onTables(snapshotTables(conn));
  onStatus("open");
  return () => {
    if (activeConnection === conn) activeConnection = null;
    conn.disconnect();
  };
}

/** The public `request_surge` reducer (anyone may call it). */
export async function callRequestSurge(customers: number, durationMin: number): Promise<void> {
  const conn = activeConnection;
  const reducer = conn?.reducers.requestSurge ?? conn?.reducers.request_surge;
  if (!reducer) throw new SpacetimeUnavailable("SpacetimeDB is not connected");
  // Generated reducer args are one object keyed by parameter name; the case policy of the bindings decides the key form.
  await reducer({ customers, duration_min: durationMin, durationMin });
}
