import type { Transport } from "@/transport";
import type { WsMessage } from "@/types";
import { useSim } from "./sim";

const FLUSH_MS = 250; // ticks arrive ~2/s per lane; render at most ~4 times per second (UI.md)

/** Subscribe to /ws and feed the store in batches. Returns a stop function. */
export function startIngest(transport: Transport): () => void {
  let buffer: WsMessage[] = [];
  const unsubscribe = transport.subscribe(
    (msg) => buffer.push(msg),
    (status) => useSim.getState().setConnection(status),
  );
  const timer = setInterval(() => {
    if (!buffer.length) return;
    const batch = buffer;
    buffer = [];
    useSim.getState().applyMessages(batch);
  }, FLUSH_MS);
  return () => {
    unsubscribe();
    clearInterval(timer);
  };
}
