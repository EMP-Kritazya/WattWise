import type { ClockState, LiveTables, SimControlRequest, WsMessage } from "@/types";
import { contextRow, escalationRow, feedRow } from "@/data/rows";
import { emptyTables } from "@/data/useLive";
import { liveRowFrames, seedLiveTables, viewerWsMessages } from "./fixtures";

const FRAME_MS = 500;
const FIXTURE_START_TS = "2026-07-18T00:30:00Z"; // the recorded scenario's first sim minute
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
    this.clear();
    this.advance(); // the first frame at once, then one per FRAME_MS
    this.resume();
    return () => this.stop();
  }

  stop() {
    clearInterval(this.timer);
    this.timer = undefined;
  }

  /** Fixture-mode simulation controls (dev and tests only): pause freezes the replay, play resumes it, reset clears it. */
  control(body: SimControlRequest): ClockState {
    if (body.action === "reset") {
      this.stop();
      this.clear();
    } else if (body.action === "pause") {
      this.stop();
    } else if (!this.timer) {
      this.resume();
    }
    const tick = this.tables.live_tick.find((row) => row.lane === "with") ?? this.tables.live_tick[0];
    return {
      playing: this.timer !== undefined,
      speed: body.speed ?? 120,
      sim_ts: tick?.ts ?? FIXTURE_START_TS,
      tick_id: tick?.tick_id ?? 0,
      paused_reason: this.timer ? null : "manual",
      day_index: 1,
      run_days: 1,
      phase: "service",
    };
  }

  /** Back to before tick 1. The table fixtures are final-state seeds for static component work, so the replay starts empty
   * and the UI never sees future decisions, agent messages, or the already-consumed surge. The backtest tables are a finished
   * run (not part of the live replay), so they stay seeded. */
  private clear() {
    this.frame = 0;
    const seed = seedLiveTables();
    this.tables = { ...emptyTables(), backtest_point: seed.backtest_point ?? [], backtest_month: seed.backtest_month ?? [] };
  }

  /** One frame per FRAME_MS from where the replay stands (play after pause continues exactly one tick later). */
  private resume() {
    this.timer = setInterval(() => this.advance(), FRAME_MS);
  }

  private advance() {
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
    const snapshot = this.snapshot();
    this.listeners.forEach((listener) => listener(snapshot, []));
  }

  private applyMessages(messages: WsMessage[]) {
    for (const message of messages) {
      if (message.type === "decision") {
        const row = feedRow(message.data, "with", message.explanation, message.explanation_source);
        this.tables.live_feed = upsert(this.tables.live_feed, [row], (r) => r.decision_id).slice(-50);
      } else if (message.type === "clock") {
        const { type: _type, ...clock } = message;
        this.tables.live_clock = [{ id: 0, ...clock, sim_host: "connected" }];
      } else if (message.type === "context") {
        this.tables.live_context = [contextRow(message.data)];
      } else if (message.type === "escalation") {
        this.tables.live_escalation = upsert(
          this.tables.live_escalation,
          [escalationRow(message.data, message.explanation, message.explanation_source)],
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
