import { create } from "zustand";
import type { LiveTables, WsMessage } from "@/types";

const emptyTables = (): LiveTables => ({
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
});

interface LiveRowState extends LiveTables {
  replaceTables: (tables: LiveTables) => void;
  applyViewerMessages: (messages: WsMessage[]) => void;
}

const upsert = <T,>(rows: T[], additions: T[], key: (row: T) => string): T[] => {
  const map = new Map(rows.map((row) => [key(row), row]));
  additions.forEach((row) => map.set(key(row), row));
  return [...map.values()];
};

/** Typed live-table hook. Screens consume these rows regardless of SpacetimeDB, fixture, or /ws source. */
export const useLive = create<LiveRowState>()((set) => ({
  ...emptyTables(),
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
      };
      for (const message of messages) {
        if (message.type === "tick") {
          const tick = message.data;
          next.live_tick = upsert(next.live_tick, [{
            lane: tick.lane,
            ts: tick.ts,
            tick_id: tick.hub.tick_id,
            total_kw: tick.meter.total_kw,
            block_avg_kw: tick.meter.block_avg_kw,
            month_peak_kw: tick.meter.month_peak_kw,
            peak_mode: tick.meter.peak_mode,
            peak_cap_kw: tick.meter.peak_cap_kw,
            target_kw: tick.meter.target_kw,
            energy_kwh_today: tick.meter.energy_kwh_today,
            price_usd_per_kwh_now: tick.meter.price_usd_per_kwh_now,
            cost_usd_today: tick.meter.cost_usd_today,
            cost_usd_month: tick.meter.cost_usd_month,
            customers_per_hour: tick.customers_per_hour,
            indoor_temp_c: tick.indoor_temp_c ?? 0,
            forecast_kw_json: tick.forecast_kw ? JSON.stringify(tick.forecast_kw) : null,
            forecast_ts: tick.forecast_kw ? tick.ts : null,
          }], (row) => row.lane);
          next.tick_history = upsert(next.tick_history, [{
            lane: tick.lane,
            ts: tick.ts,
            total_kw: tick.meter.total_kw,
            block_avg_kw: tick.meter.block_avg_kw,
          }], (row) => `${row.lane}:${row.ts}`).slice(-360);
          next.live_device = upsert(next.live_device, tick.hub.devices.map((device) => ({
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
            physical_json: device.physical ? JSON.stringify(device.physical) : null,
          })), (row) => row.key);
        } else if (message.type === "comparison") {
          next.live_comparison = [{ id: 0, ...message.data }];
        } else if (message.type === "decision") {
          const decision = message.data;
          next.live_feed = upsert(next.live_feed, [{
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
          }], (row) => row.decision_id).slice(-50);
        } else if (message.type === "clock") {
          next.live_clock = [{
            id: 0,
            playing: message.playing,
            speed: message.speed,
            sim_ts: message.sim_ts,
            tick_id: message.tick_id,
            paused_reason: message.paused_reason,
            slowed_reason: message.slowed_reason,
            sim_host: message.paused_reason === "sim_host_offline" ? "offline" : "connected",
          }];
        } else if (message.type === "context") {
          const context = message.data;
          const weather = context.weather?.hourly[0];
          const price = context.prices?.hourly[0];
          const event = context.events?.items[0];
          next.live_context = [{
            id: 0,
            weather_summary: weather ? `${weather.temp_c} °C now` : "Unavailable",
            weather_label: context.weather?.label ?? "recorded",
            prices_summary: price ? `${price.usd_per_kwh} USD/kWh now, stress ${context.prices?.stress ?? "normal"}` : "Unavailable",
            prices_label: context.prices?.label ?? "recorded",
            events_summary: event ? `${event.name} at ${event.venue}, ${event.distance_km} km` : "No nearby events",
            events_label: context.events?.label ?? "recorded",
            crowd_effect: context.crowd_effect?.value ?? "none",
          }];
        } else if (message.type === "escalation") {
          const escalation = message.data;
          next.live_escalation = upsert(next.live_escalation, [{
            escalation_id: escalation.escalation_id,
            lane: escalation.lane,
            status: escalation.status,
            problem_json: JSON.stringify(escalation.problem),
            options_json: JSON.stringify(escalation.options),
            chosen_option_id: escalation.chosen_option_id,
            resolved_by: escalation.resolved_by,
            rationale: escalation.rationale,
          }], (row) => row.escalation_id).slice(-20);
        } else if (message.type === "agent_log") {
          const id = Math.max(0, ...next.live_agent_log.map((row) => row.id)) + 1;
          next.live_agent_log = [...next.live_agent_log, { id, ...message.data }].slice(-300);
        }
      }
      return next;
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

export function ingestViewerMessages(messages: WsMessage[]) {
  if (import.meta.env.VITE_MOCKS === "1") return;
  useLive.getState().applyViewerMessages(messages);
}
