import { useSim, type LiveSourceKind } from "@/store/sim";
import { transport } from "@/transport";
import type { LiveTables, WsMessage } from "@/types";
import { callRequestSurge, connectSpacetime } from "./spacetime";
import { ingestViewerMessages, startLiveRows, useLive } from "./useLive";

const FLUSH_MS = 250; // ticks arrive ~2/s per lane; render at most ~4 times per second (UI.md)

/**
 * Which live source to use (UI.md "Where live data comes from"): the one the backend publishes on, read from
 * `GET /api/health` (`live_transport`), so a viewer can never listen where nothing is sent:
 *   spacetime → SpacetimeDB tables, falling back to /ws if it can't connect
 *   ws        → everything over /ws
 *   mock mode → the in-browser mock server
 * VITE_LIVE_TRANSPORT only decides when the health call fails. VITE_SPACETIME_URI / _DB default to the backend
 * client's own defaults (port 3000 on this host, database `wattwise`).
 */
const wanted = (import.meta.env.VITE_LIVE_TRANSPORT ?? "spacetime") as "spacetime" | "ws";
const spacetimeUri: string =
  import.meta.env.VITE_SPACETIME_URI ?? `${location.protocol === "https:" ? "wss" : "ws"}://${location.hostname}:3000`;
const spacetimeDb: string = import.meta.env.VITE_SPACETIME_DB ?? "wattwise";
const spacetimeToken: string | undefined = import.meta.env.VITE_SPACETIME_TOKEN;

async function backendTransport(): Promise<"spacetime" | "ws"> {
  try {
    return (await transport.health()).live_transport;
  } catch {
    return wanted;
  }
}

/** Start live data. Chat, proposals and escalation notices always come over /ws as well. Returns a stop function. */
export function startLive(): () => void {
  const stopRows = startLiveRows();
  let buffer: WsMessage[] = []; // /ws (and mock) messages: legacy screen store + row store
  let tableBuffer: WsMessage[] = []; // messages derived from SpacetimeDB rows: legacy screen store only
  let latestTables: LiveTables | null = null; // newest SpacetimeDB snapshot, written to the row store on flush
  const pushFromTables = (msgs: WsMessage[]) => {
    if (spacetimeDisabled || stopped) return;
    tableBuffer.push(...msgs);
  };
  const timer = setInterval(() => {
    if (latestTables) {
      useLive.getState().replaceTables(latestTables);
      latestTables = null;
    }
    if (tableBuffer.length) {
      const batch = tableBuffer;
      tableBuffer = [];
      useSim.getState().applyMessages(batch);
    }
    if (!buffer.length) return;
    const batch = buffer;
    buffer = [];
    useSim.getState().applyMessages(batch);
    ingestViewerMessages(batch);
  }, FLUSH_MS);

  const setSource = (kind: LiveSourceKind) => useSim.getState().setLiveSource(kind);
  let usingSpacetime = false;
  let spacetimeDisabled = false;
  let stopped = false;
  let stopSpacetime: (() => void) | undefined;

  // /ws always runs: it's the fallback, and it carries chat streaming and proposals in every mode.
  const stopWs = transport.subscribe(
    (msg) => {
      if (msg.type === "warning" && msg.code === "live_transport_down") {
        spacetimeDisabled = true;
        usingSpacetime = false;
        stopSpacetime?.();
        stopSpacetime = undefined;
        latestTables = null;
        tableBuffer = [];
        setSource("ws");
      }
      // With SpacetimeDB live, its tables are the source of truth for ticks, feed, clock and comparison.
      if (usingSpacetime && LIVE_TABLE_TYPES.has(msg.type)) return;
      buffer.push(msg);
    },
    (status) => useSim.getState().setConnection(status),
  );
  setSource(transport.kind === "mock" ? "mock" : "ws");

  const startSpacetime = () => connectSpacetime(
      { uri: spacetimeUri, database: spacetimeDb, token: spacetimeToken },
      (tables) => {
        if (spacetimeDisabled || stopped) return;
        latestTables = tables;
      },
      pushFromTables,
      () => {},
    )
      .then((stop) => {
        if (spacetimeDisabled || stopped) { stop(); return; }
        usingSpacetime = true;
        stopSpacetime = stop;
        setSource("spacetime");
      })
      .catch((err) => {
        console.warn("SpacetimeDB unavailable, staying on /ws:", err);
        buffer.push({
          type: "warning",
          code: "live_transport_down",
          message: "Live sync is down, so this screen is following the server directly. Other viewers may lag.",
          data: {},
        });
      });
  if (transport.kind !== "mock") {
    void backendTransport().then((kind) => {
      if (kind === "spacetime" && !stopped) startSpacetime();
    });
  }

  return () => {
    stopped = true;
    stopWs();
    stopSpacetime?.();
    stopRows();
    clearInterval(timer);
  };
}

/** Message types that SpacetimeDB carries when it's the live source (CONTRACTS.md section 5). */
const LIVE_TABLE_TYPES = new Set<WsMessage["type"]>([
  "tick", "decision", "clock", "comparison", "context", "escalation", "agent_log", "backtest_point", "backtest_month",
]);

/** Add customers. Over SpacetimeDB anyone (even a judge's phone) can call `request_surge`; otherwise REST. */
export async function requestSurge(customers: number, durationMin = 60): Promise<void> {
  if (import.meta.env.VITE_MOCKS === "1") {
    const { requestSurgeReducer } = await import("@/mocks/spacetimeReducers");
    await requestSurgeReducer(customers, durationMin);
    return;
  }
  if (useSim.getState().liveSource === "spacetime") {
    try {
      await callRequestSurge(customers, durationMin);
      return;
    } catch (err) {
      console.warn("request_surge failed, using REST:", err);
    }
  }
  await transport.addCustomers({ customers, duration_min: durationMin });
}
