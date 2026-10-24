import { create } from "zustand";
import type { ConnectionStatus } from "@/transport";
import type { ClockState, Decision, Device, EquipmentType, KitchenView, Lane, TickState, WsMessage, WsMessageType } from "@/types";

const HISTORY_MS = 3 * 60 * 60_000; // keep the last 3 sim hours per lane (UI.md)
const MAX_BLOCKS = 96; // one day of 15-minute blocks

export interface LanePoint {
  t: number;
  total_kw: number;
  block_avg_kw: number;
}

/** A 15-minute demand block as the meter reported it (the last block_avg_kw seen for that block_start). */
export interface BlockPoint {
  start: number;
  avg_kw: number;
}

export interface FeedItem {
  decision: Decision;
  explanation: string;
  explanation_source: "ai" | "template";
}

export interface PendingApproval {
  decision: Decision;
  explanation: string;
  expires_at: string;
}

export interface Warning {
  code: string;
  message: string;
  data: Record<string, unknown>;
}

export interface ChatMessage {
  id: string;
  role: "owner" | "assistant";
  text: string;
  done: boolean;
}

interface SimState {
  connection: ConnectionStatus;
  catalog: EquipmentType[] | null;
  kitchen: KitchenView | null;
  clock: ClockState | null;
  latest: Record<Lane, TickState | null>;
  history: Record<Lane, LanePoint[]>;
  blocks: Record<Lane, BlockPoint[]>;
  forecast: { from_ts: string; kw: number[] } | null;
  /** By decision_id. Fed by `decision` / `approval_request` messages, which carry the explanation. */
  feed: Record<string, FeedItem>;
  approval: PendingApproval | null;
  warning: Warning | null;
  chat: ChatMessage[];
  backtestProgress: Record<string, { month: string; pct: number }>;
  messageCounts: Partial<Record<WsMessageType, number>>;

  setConnection: (status: ConnectionStatus) => void;
  setCatalog: (catalog: EquipmentType[]) => void;
  setKitchen: (kitchen: KitchenView | null) => void;
  /** A REST reply returned one device (e.g. after an importance change). */
  updateDevice: (device: Device) => void;
  /** Drop everything from the previous run (call before building a new kitchen). */
  clearRun: () => void;
  /** A REST reply (approve, undo, list) changed a decision: keep its explanation, update the rest. */
  upsertDecisions: (decisions: Decision[]) => void;
  addOwnerChat: (text: string) => void;
  dismissWarning: () => void;
  /** Apply a batch of /ws messages in one state update. */
  applyMessages: (msgs: WsMessage[]) => void;
}

const emptyLanes = () => ({
  latest: { without: null, with: null },
  history: { without: [], with: [] },
  blocks: { without: [], with: [] },
});

export const useSim = create<SimState>()((set) => ({
  connection: "connecting",
  catalog: null,
  kitchen: null,
  clock: null,
  ...emptyLanes(),
  forecast: null,
  feed: {},
  approval: null,
  warning: null,
  chat: [],
  backtestProgress: {},
  messageCounts: {},

  setConnection: (connection) => set({ connection }),

  setCatalog: (catalog) => set({ catalog }),

  setKitchen: (kitchen) => set({ kitchen }),

  updateDevice: (device) =>
    set((s) =>
      s.kitchen
        ? { kitchen: { ...s.kitchen, devices: s.kitchen.devices.map((d) => (d.device_id === device.device_id ? device : d)) } }
        : {},
    ),

  clearRun: () => set({ ...emptyLanes(), forecast: null, feed: {}, approval: null, warning: null }),

  upsertDecisions: (decisions) =>
    set((s) => {
      const feed = { ...s.feed };
      for (const d of decisions) {
        const prev = feed[d.decision_id];
        feed[d.decision_id] = prev ? { ...prev, decision: d } : { decision: d, explanation: "", explanation_source: "template" };
      }
      const approval = s.approval && feed[s.approval.decision.decision_id]?.decision.status !== "awaiting_approval" ? null : s.approval;
      return { feed, approval };
    }),

  addOwnerChat: (text) =>
    set((s) => ({ chat: [...s.chat, { id: `owner_${s.chat.length}`, role: "owner", text, done: true }] })),

  dismissWarning: () => set({ warning: null }),

  applyMessages: (msgs) =>
    set((s) => {
      const latest = { ...s.latest };
      const fresh: Record<Lane, LanePoint[]> = { without: [], with: [] };
      const feed = { ...s.feed };
      const chat = [...s.chat];
      const messageCounts = { ...s.messageCounts };
      const backtestProgress = { ...s.backtestProgress };
      const blocks = { ...s.blocks };
      let { clock, forecast, approval, warning } = s;

      for (const m of msgs) {
        messageCounts[m.type] = (messageCounts[m.type] ?? 0) + 1;
        switch (m.type) {
          case "tick": {
            const t = m.data;
            latest[t.lane] = t;
            fresh[t.lane].push({ t: Date.parse(t.ts), total_kw: t.meter.total_kw, block_avg_kw: t.meter.block_avg_kw });
            if (t.forecast_kw) forecast = { from_ts: t.ts, kw: t.forecast_kw };
            // Keep the latest block_avg_kw per block_start; once a block closes, that's its final average.
            const start = Date.parse(t.meter.block_start);
            const list = blocks[t.lane];
            const last = list[list.length - 1];
            const point = { start, avg_kw: t.meter.block_avg_kw };
            if (last && start < last.start) blocks[t.lane] = [point]; // sim time went backwards: reset
            else if (last && start === last.start) blocks[t.lane] = [...list.slice(0, -1), point];
            else blocks[t.lane] = [...list, point].slice(-MAX_BLOCKS);
            // t.new_decisions also arrive as `decision` / `approval_request` messages; those drive the feed.
            break;
          }
          case "decision":
            feed[m.data.decision_id] = { decision: m.data, explanation: m.explanation, explanation_source: m.explanation_source };
            if (approval?.decision.decision_id === m.data.decision_id && m.data.status !== "awaiting_approval") approval = null;
            break;
          case "approval_request":
            approval = { decision: m.data, explanation: m.explanation, expires_at: m.expires_at };
            // CONTRACTS.md gives approval_request no explanation_source; treat it as template text.
            feed[m.data.decision_id] = { decision: m.data, explanation: m.explanation, explanation_source: "template" };
            break;
          case "clock":
            clock = { playing: m.playing, speed: m.speed, sim_ts: m.sim_ts, paused_reason: m.paused_reason };
            break;
          case "warning":
            warning = { code: m.code, message: m.message, data: m.data };
            break;
          case "chat_delta": {
            const i = chat.findIndex((c) => c.id === m.chat_id);
            if (i < 0) chat.push({ id: m.chat_id, role: "assistant", text: m.text, done: false });
            else chat[i] = { ...chat[i], text: chat[i].text + m.text };
            break;
          }
          case "chat_done": {
            const i = chat.findIndex((c) => c.id === m.chat_id);
            if (i < 0) chat.push({ id: m.chat_id, role: "assistant", text: "", done: true });
            else chat[i] = { ...chat[i], done: true };
            break;
          }
          case "backtest_progress":
            backtestProgress[m.run_id] = { month: m.month, pct: m.pct };
            break;
        }
      }

      const history = { ...s.history };
      for (const lane of ["without", "with"] as const) {
        if (!fresh[lane].length) continue;
        const prev = history[lane];
        // Sim time going backwards means the run was reset: start the lane's history over.
        const restarted = prev.length > 0 && fresh[lane][0].t < prev[prev.length - 1].t;
        const all = restarted ? fresh[lane] : prev.concat(fresh[lane]);
        const cutoff = all[all.length - 1].t - HISTORY_MS;
        const first = all.findIndex((p) => p.t >= cutoff);
        history[lane] = first > 0 ? all.slice(first) : all;
      }

      return { latest, history, blocks, feed, chat, messageCounts, backtestProgress, clock, forecast, approval, warning };
    }),
}));
