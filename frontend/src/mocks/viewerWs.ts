import type { ConnectionStatus } from "@/transport";
import type { WsMessage } from "@/types";
import { viewerWsMessages } from "./fixtures";

const FRAME_MS = 500; // fixture scenario is recorded at 120×: one simulated minute per 0.5 s
const listeners = new Set<(message: WsMessage) => void>();

const frames = (() => {
  const out: WsMessage[][] = [[]];
  for (const message of viewerWsMessages) {
    if (message.type === "tick" && message.data.lane === "without" && out[out.length - 1].length) out.push([]);
    out[out.length - 1].push(message);
  }
  return out.filter((frame) => frame.length);
})();

export function broadcastFixtureMessage(message: WsMessage) {
  for (const listener of listeners) listener(structuredClone(message));
}

/** Replays the shared viewer fixture in contract order. Each subscriber gets a fresh deterministic run. */
export function subscribeFixtureViewer(
  onMessage: (message: WsMessage) => void,
  onStatus: (status: ConnectionStatus) => void,
): () => void {
  let frame = 0;
  let timer: ReturnType<typeof setInterval> | undefined;
  let stopped = false;
  onStatus("connecting");

  const start = setTimeout(() => {
    if (stopped) return;
    listeners.add(onMessage);
    onStatus("open");
    const publish = () => {
      const current = frames[frame++];
      if (!current) {
        clearInterval(timer);
        return;
      }
      current.forEach(onMessage);
    };
    publish();
    timer = setInterval(publish, FRAME_MS);
  }, 20);

  return () => {
    stopped = true;
    clearTimeout(start);
    clearInterval(timer);
    listeners.delete(onMessage);
    onStatus("closed");
  };
}
