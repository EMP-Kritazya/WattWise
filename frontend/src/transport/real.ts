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
  setPeakCap: (body) => request("PUT", "/api/kitchen/peak-cap", body),
  simControl: (body) => request("POST", "/api/sim/control", body),
  deviceCommand: (deviceId, body) => request("POST", `/api/devices/${enc(deviceId)}/command`, body),
  addCustomers: (body) => request("POST", "/api/events/customers", body),
  undo: (decisionId) => request("POST", `/api/decisions/${enc(decisionId)}/undo`),
  listDecisions: (limit = 50) => request("GET", `/api/decisions?limit=${limit}`),
  runBacktest: (body) => request("POST", "/api/backtest/run", body),
  getBacktest: (runId) => request("GET", `/api/backtest/${enc(runId)}`),
  chat: (message) => request("POST", "/api/chat", { message }),
  listProposals: (status = "pending") => request("GET", `/api/proposals?status=${status}`),
  confirmProposal: (proposalId, confirm) => request("POST", `/api/proposals/${enc(proposalId)}/confirm`, { confirm }),
  setAuthority: (authority) => request("PUT", "/api/kitchen/authority", authority),
  setPreferences: (text) => request("PUT", "/api/kitchen/preferences", { text }),
  getContext: () => request("GET", "/api/context"),
  listEscalations: (status = "open") => request("GET", `/api/escalations?status=${status}`),
  health: () => request("GET", "/api/health"),

  subscribe(onMessage, onStatus) {
    let socket: WebSocket | null = null;
    let retryMs = 500;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;

    const setStatus = (s: ConnectionStatus) => onStatus(s);

    const connect = () => {
      if (stopped) return;
      setStatus("connecting");
      const scheme = location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${scheme}://${location.host}/ws`);
      socket.onopen = () => {
        if (stopped) { socket?.close(); return; }
        retryMs = 500;
        setStatus("open");
      };
      socket.onmessage = (ev) => {
        if (stopped) return;
        try {
          onMessage(JSON.parse(ev.data) as WsMessage);
        } catch (err) {
          console.warn("Dropped a WebSocket message that isn't JSON", err);
        }
      };
      socket.onclose = () => {
        if (stopped) return;
        setStatus("closed");
        // Back off up to 5 s so a restarting API server doesn't get hammered.
        retryTimer = setTimeout(connect, retryMs);
        retryMs = Math.min(retryMs * 2, 5000);
      };
    };

    // StrictMode immediately cleans up its first effect. Let it cancel before opening a socket.
    retryTimer = setTimeout(connect, 0);
    return () => {
      stopped = true;
      clearTimeout(retryTimer);
      if (socket?.readyState === WebSocket.OPEN) socket.close();
      // A pending handshake closes in onopen; closing CONNECTING sockets emits a browser error.
    };
  },
};
