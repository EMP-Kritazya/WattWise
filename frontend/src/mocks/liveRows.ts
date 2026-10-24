import type { Context, LiveTables, WsMessage } from "@/types";
import { liveRowFrames, seedLiveTables, viewerWsMessages } from "./fixtures";

const FRAME_MS = 500;
type Listener = (tables: LiveTables, messages: WsMessage[]) => void;

const messageFrames = (() => {
  const byTick = new Map<number, WsMessage[]>();
  let tick = 0;
  for (const message of viewerWsMessages) {
    if (message.type === "tick") {
      tick = message.data.hub.tick_id;
      continue;
    }
    if (message.type === "comparison") continue;
    byTick.set(tick, [...(byTick.get(tick) ?? []), message]);
  }
  return byTick;
})();

const upsert = <T,>(rows: T[], additions: T[], key: (row: T) => string): T[] => {
  const map = new Map(rows.map((row) => [key(row), row]));
  additions.forEach((row) => map.set(key(row), row));
  return [...map.values()];
};

const contextSummary = (context: Context): LiveTables["live_context"][number] => ({
  id: 0,
  weather_summary: context.weather?.hourly[0] ? `${context.weather.hourly[0].temp_c} °C now` : "Unavailable",
  weather_label: context.weather?.label ?? "recorded",
  prices_summary: context.prices?.hourly[0]
    ? `${context.prices.hourly[0].usd_per_kwh} USD/kWh now, stress ${context.prices.stress}`
    : "Unavailable",
  prices_label: context.prices?.label ?? "recorded",
  events_summary: context.events?.items[0]
    ? `${context.events.items[0].name} at ${context.events.items[0].venue}, ${context.events.items[0].distance_km} km`
    : "No nearby events",
  events_label: context.events?.label ?? "recorded",
  crowd_effect: context.crowd_effect?.value ?? "none",
});

class FixtureLiveRows {
  private tables = seedLiveTables();
  private listeners = new Set<Listener>();
  private timer: ReturnType<typeof setInterval> | undefined;
  private frame = 0;

  snapshot(): LiveTables {
    return structuredClone(this.tables);
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    listener(this.snapshot(), []);
    return () => this.listeners.delete(listener);
  }

  start(): () => void {
    if (this.timer) return () => this.stop();
    this.frame = 0;
    // The table fixtures are final-state seeds for static component work. Clear them before replay so the UI never sees
    // future decisions, agent messages, or the already-consumed surge.
    this.tables = {
      live_tick: [], tick_history: [], live_device: [], live_comparison: [], live_feed: [],
      live_clock: [], live_context: [], live_escalation: [], live_agent_log: [], surge_request: [],
    };
    const advance = () => {
      const payload = liveRowFrames[this.frame++];
      if (!payload) {
        this.stop();
        return;
      }
      this.tables.live_tick = structuredClone(payload.live_tick);
      this.tables.tick_history = upsert(this.tables.tick_history, payload.tick_history, (row) => `${row.lane}:${row.ts}`).slice(-360);
      this.tables.live_device = upsert(this.tables.live_device, payload.live_device, (row) => row.key);
      this.tables.live_comparison = [structuredClone(payload.live_comparison)];
      const tickId = payload.live_tick[0]?.tick_id ?? 0;
      const messages = [...(this.frame === 1 ? messageFrames.get(0) ?? [] : []), ...(messageFrames.get(tickId) ?? [])];
      this.applyMessages(messages);
      const snapshot = this.snapshot();
      this.listeners.forEach((listener) => listener(snapshot, structuredClone(messages)));
    };
    advance();
    this.timer = setInterval(advance, FRAME_MS);
    return () => this.stop();
  }

  stop() {
    clearInterval(this.timer);
    this.timer = undefined;
  }

  requestSurge(customers: number, durationMin: number) {
    const id = Math.max(0, ...this.tables.surge_request.map((row) => row.id)) + 1;
    this.tables.surge_request.push({
      id,
      customers,
      duration_min: durationMin,
      requested_by: "fixture_viewer",
      created_at: new Date().toISOString(),
      consumed: false,
    });
  }

  private applyMessages(messages: WsMessage[]) {
    for (const message of messages) {
      if (message.type === "decision") {
        const decision = message.data;
        this.tables.live_feed = upsert(
          this.tables.live_feed,
          [{
            decision_id: decision.decision_id,
            lane: "with" as const,
            ts: decision.ts,
            device_id: decision.device_id,
            action: decision.action,
            value: decision.value,
            status: decision.status,
            reason_code: decision.reason_code,
            effect_json: JSON.stringify(decision.effect),
            explanation: message.explanation,
            explanation_source: message.explanation_source,
          }],
          (row) => row.decision_id,
        ).slice(-50);
      } else if (message.type === "clock") {
        this.tables.live_clock = [{
          id: 0,
          playing: message.playing,
          speed: message.speed,
          sim_ts: message.sim_ts,
          tick_id: message.tick_id,
          paused_reason: message.paused_reason,
          slowed_reason: message.slowed_reason,
          sim_host: "connected",
        }];
      } else if (message.type === "context") {
        this.tables.live_context = [contextSummary(message.data)];
      } else if (message.type === "escalation") {
        const escalation = message.data;
        this.tables.live_escalation = upsert(
          this.tables.live_escalation,
          [{
            escalation_id: escalation.escalation_id,
            lane: escalation.lane,
            status: escalation.status,
            problem_json: JSON.stringify(escalation.problem),
            options_json: JSON.stringify(escalation.options),
            chosen_option_id: escalation.chosen_option_id,
            resolved_by: escalation.resolved_by,
            rationale: escalation.rationale,
          }],
          (row) => row.escalation_id,
        ).slice(-20);
      } else if (message.type === "agent_log") {
        const id = Math.max(0, ...this.tables.live_agent_log.map((row) => row.id)) + 1;
        this.tables.live_agent_log = [...this.tables.live_agent_log, { id, ...message.data }].slice(-300);
      }
    }
  }
}

export const fixtureLiveRows = new FixtureLiveRows();
