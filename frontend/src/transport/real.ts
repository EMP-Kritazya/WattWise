import type { WsMessage } from "@/types";
import { ApiError } from "./errors";
import type { ConnectionStatus, Transport } from "./types";

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    // FastAPI puts the reason in `detail` (e.g. the engine's RuleError message on 422).
    const payload = await res.json().catch(() => null);
    const detail = payload?.detail;
    throw new ApiError(res.status, typeof detail === "string" ? detail : `${method} ${path} failed (${res.status})`);
  }
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

const enc = encodeURIComponent;

/** Talks to the FastAPI server through the Vite proxy (/api and /ws). */
export const realTransport: Transport = {
  kind: "real",

  getCatalog: () => request("GET", "/api/catalog"),
  createKitchen: (config) => request("POST", "/api/kitchen", config),
  getKitchen: () => request("GET", "/api/kitchen"),
  setImportance: (deviceId, body) => request("PUT", `/api/kitchen/devices/${enc(deviceId)}/importance`, body),
  setPeakCap: (peak_cap_kw) => request("PUT", "/api/kitchen/peak-cap", { peak_cap_kw }),
  simControl: (body) => request("POST", "/api/sim/control", body),
  deviceCommand: (deviceId, body) => request("POST", `/api/devices/${enc(deviceId)}/command`, body),
  addCustomers: (body) => request("POST", "/api/events/customers", body),
  approve: (decisionId, approve) => request("POST", `/api/decisions/${enc(decisionId)}/approve`, { approve }),
  undo: (decisionId) => request("POST", `/api/decisions/${enc(decisionId)}/undo`),
  listDecisions: (limit = 50) => request("GET", `/api/decisions?limit=${limit}`),
  runBacktest: (body) => request("POST", "/api/backtest/run", body),
  getBacktest: (runId) => request("GET", `/api/backtest/${enc(runId)}`),
  chat: (message) => request("POST", "/api/chat", { message }),

  subscribe(onMessage, onStatus) {
    let socket: WebSocket | null = null;
    let retryMs = 500;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;

    const setStatus = (s: ConnectionStatus) => onStatus(s);

    const connect = () => {
      setStatus("connecting");
      const scheme = location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${scheme}://${location.host}/ws`);
      socket.onopen = () => {
        retryMs = 500;
        setStatus("open");
      };
      socket.onmessage = (ev) => {
        try {
          onMessage(JSON.parse(ev.data) as WsMessage);
        } catch (err) {
          console.warn("Dropped a WebSocket message that isn't JSON", err);
        }
      };
      socket.onclose = () => {
        setStatus("closed");
        if (stopped) return;
        // Back off up to 5 s so a restarting API server doesn't get hammered.
        retryTimer = setTimeout(connect, retryMs);
        retryMs = Math.min(retryMs * 2, 5000);
      };
    };

    connect();
    return () => {
      stopped = true;
      clearTimeout(retryTimer);
      socket?.close();
    };
  },
};
