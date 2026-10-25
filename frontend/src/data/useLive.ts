import { create } from "zustand";
import type { Lane, LiveTables, WsMessage } from "@/types";
import {
  backtestMonthRow,
  backtestPointRow,
  contextRow,
  escalationRow,
  feedRow,
  liveDeviceRows,
  liveTickRow,
  tickHistoryRow,
  upsertRun,
} from "./rows";

export const emptyTables = (): LiveTables => ({
  live_tick: [],
  tick_history: [],
  live_device: [],
  live_comparison: [],
  live_feed: [],
  live_clock: [],
  live_context: [],
  live_escalation: [],
  live_agent_log: [],
  surge_request: [],
  backtest_point: [],
  backtest_month: [],
});

interface LiveRowState extends LiveTables {
  /** Each lane's latest forecast and the ts of the decision tick that made it (kept between decision ticks). */
  forecasts: Record<Lane, { kw: number[] | null; ts: string | null }>;
  replaceTables: (tables: LiveTables) => void;
  applyViewerMessages: (messages: WsMessage[]) => void;
}

const upsert = <T,>(rows: T[], additions: T[], key: (row: T) => string): T[] => {
  const map = new Map(rows.map((row) => [key(row), row]));
  additions.forEach((row) => map.set(key(row), row));
  return [...map.values()];
};

const TICK_HISTORY_ROWS = 360; // 180 sim minutes × 2 lanes (CONTRACTS.md section 5)

/**
 * Typed live-table hook: the section 5 rows, whatever the source (SpacetimeDB tables replace them wholesale; /ws and the
 * fixture mock are mapped into the same rows by src/data/rows.ts). Screens read rows only; they never compute.
 */
export const useLive = create<LiveRowState>()((set) => ({
  ...emptyTables(),
  forecasts: { without: { kw: null, ts: null }, with: { kw: null, ts: null } },
  replaceTables: (tables) => set(structuredClone(tables)),
  applyViewerMessages: (messages) =>
    set((state) => {
      const next: LiveTables = {
        live_tick: [...state.live_tick],
        tick_history: [...state.tick_history],
        live_device: [...state.live_device],
        live_comparison: [...state.live_comparison],
        live_feed: [...state.live_feed],
        live_clock: [...state.live_clock],
        live_context: [...state.live_context],
        live_escalation: [...state.live_escalation],
        live_agent_log: [...state.live_agent_log],
        surge_request: [...state.surge_request],
        backtest_point: [...state.backtest_point],
        backtest_month: [...state.backtest_month],
      };
      const forecasts = { ...state.forecasts };
      for (const message of messages) {
        if (message.type === "tick") {
          const tick = message.data;
          if (tick.forecast_kw) forecasts[tick.lane] = { kw: tick.forecast_kw, ts: tick.ts };
          const fc = forecasts[tick.lane];
          next.live_tick = upsert(next.live_tick, [liveTickRow(tick, fc.kw, fc.ts)], (row) => row.lane);
          next.tick_history = upsert(next.tick_history, [tickHistoryRow(tick)], (row) => `${row.lane}:${row.ts}`).slice(
            -TICK_HISTORY_ROWS,
          );
          next.live_device = upsert(next.live_device, liveDeviceRows(tick), (row) => row.key);
        } else if (message.type === "comparison") {
          next.live_comparison = [{ id: 0, ...message.data }];
        } else if (message.type === "decision") {
          // /ws decision messages carry no lane; only the with lane decides (owner overrides of the without lane are not fed)
          const row = feedRow(message.data, "with", message.explanation, message.explanation_source);
          next.live_feed = upsert(next.live_feed, [row], (r) => r.decision_id).slice(-50);
        } else if (message.type === "clock") {
          const { type: _type, ...clock } = message;
          next.live_clock = [{
            id: 0,
            ...clock,
            sim_host: message.paused_reason === "sim_host_offline" ? "offline" : "connected",
          }];
        } else if (message.type === "context") {
          next.live_context = [contextRow(message.data)];
        } else if (message.type === "escalation") {
          next.live_escalation = upsert(next.live_escalation, [escalationRow(message.data, message.explanation, message.explanation_source)], (row) => row.escalation_id).slice(-20);
        } else if (message.type === "agent_log") {
          const id = Math.max(0, ...next.live_agent_log.map((row) => row.id)) + 1;
          next.live_agent_log = [...next.live_agent_log, { id, ...message.data }].slice(-300);
        } else if (message.type === "backtest_point") {
          next.backtest_point = upsertRun(next.backtest_point, [backtestPointRow(message.run_id, message.data)]);
          if (next.backtest_month.some((r) => r.run_id !== message.run_id)) {
            next.backtest_month = next.backtest_month.filter((r) => r.run_id === message.run_id);
          }
        } else if (message.type === "backtest_month") {
          next.backtest_month = upsertRun(next.backtest_month, [backtestMonthRow(message.run_id, message.data)]);
          if (next.backtest_point.some((r) => r.run_id !== message.run_id)) {
            next.backtest_point = next.backtest_point.filter((r) => r.run_id === message.run_id);
          }
        }
      }
      return { ...next, forecasts };
    }),
}));

export function startLiveRows(): () => void {
  if (import.meta.env.VITE_MOCKS !== "1") return () => {};
  let cancelled = false;
  let cleanup: (() => void) | undefined;
  void import("@/mocks/liveRows").then(({ fixtureLiveRows }) => {
    if (cancelled) return;
    const unsubscribe = fixtureLiveRows.subscribe((tables) => useLive.getState().replaceTables(tables));
    const stop = fixtureLiveRows.start();
    cleanup = () => {
      unsubscribe();
      stop();
    };
  });
  return () => {
    cancelled = true;
    cleanup?.();
  };
}

/** /ws messages into the row store (not in mock mode, which feeds rows itself, nor when SpacetimeDB is the source). */
export function ingestViewerMessages(messages: WsMessage[]) {
  if (import.meta.env.VITE_MOCKS === "1") return;
  useLive.getState().applyViewerMessages(messages);
}
