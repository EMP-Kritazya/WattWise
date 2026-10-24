import { useSim, type LiveSourceKind } from "@/store/sim";
import { transport } from "@/transport";
import type { WsMessage } from "@/types";
import { callRequestSurge, connectSpacetime } from "./spacetime";

const FLUSH_MS = 250; // ticks arrive ~2/s per lane; render at most ~4 times per second (UI.md)

/**
 * Which live source to use (UI.md "Where live data comes from"):
 *   VITE_LIVE_TRANSPORT=spacetime (default) → SpacetimeDB tables, falling back to /ws if it can't connect
 *   VITE_LIVE_TRANSPORT=ws                  → everything over /ws
 *   mock mode                               → the in-browser mock server
 */
const wanted = (import.meta.env.VITE_LIVE_TRANSPORT ?? "spacetime") as "spacetime" | "ws";
const spacetimeUri: string | undefined = import.meta.env.VITE_SPACETIME_URI;
const spacetimeDb: string | undefined = import.meta.env.VITE_SPACETIME_DB;

/** Start live data. Chat, proposals and escalation choices always come over /ws as well. Returns a stop function. */
export function startLive(): () => void {
  let buffer: WsMessage[] = [];
  const push = (msgs: WsMessage[]) => {
    buffer.push(...msgs);
  };
  const timer = setInterval(() => {
    if (!buffer.length) return;
    const batch = buffer;
    buffer = [];
    useSim.getState().applyMessages(batch);
  }, FLUSH_MS);

  const setSource = (kind: LiveSourceKind) => useSim.getState().setLiveSource(kind);
  let usingSpacetime = false;
  let stopSpacetime: (() => void) | undefined;

  // /ws always runs: it's the fallback, and it carries chat streaming and proposals in every mode.
  const stopWs = transport.subscribe(
    (msg) => {
      // With SpacetimeDB live, its tables are the source of truth for ticks, feed, clock and comparison.
      if (usingSpacetime && LIVE_TABLE_TYPES.has(msg.type)) return;
      buffer.push(msg);
    },
    (status) => useSim.getState().setConnection(status),
  );
  setSource(transport.kind === "mock" ? "mock" : "ws");

  if (transport.kind !== "mock" && wanted === "spacetime" && spacetimeUri && spacetimeDb) {
    connectSpacetime({ uri: spacetimeUri, database: spacetimeDb }, push, () => {})
      .then((stop) => {
        usingSpacetime = true;
        stopSpacetime = stop;
        setSource("spacetime");
      })
      .catch((err) => {
        console.warn("SpacetimeDB unavailable, staying on /ws:", err);
        push([
          {
            type: "warning",
            code: "live_transport_down",
            message: "Live sync is down, so this screen is following the server directly. Other viewers may lag.",
            data: {},
          },
        ]);
      });
  }

  return () => {
    stopWs();
    stopSpacetime?.();
    clearInterval(timer);
  };
}

/** Message types that SpacetimeDB carries when it's the live source (CONTRACTS.md section 5). */
const LIVE_TABLE_TYPES = new Set<WsMessage["type"]>(["tick", "decision", "clock", "comparison", "context", "escalation", "agent_log"]);

/** Add customers. Over SpacetimeDB anyone (even a judge's phone) can call `request_surge`; otherwise REST. */
export async function requestSurge(customers: number, durationMin = 60): Promise<void> {
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
