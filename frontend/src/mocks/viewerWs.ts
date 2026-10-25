import type { ConnectionStatus } from "@/transport";
import type { ClockState, SimControlRequest, WsMessage } from "@/types";
import { viewerWsMessages } from "./fixtures";

const listeners = new Set<(message: WsMessage) => void>();

const frames = (() => {
  const out: WsMessage[][] = [[]];
  for (const message of viewerWsMessages) {
    if (message.type === "tick" && message.data.lane === "without" && out[out.length - 1].length) out.push([]);
    out[out.length - 1].push(message);
  }
  return out.filter((frame) => frame.length);
})();

const initialClock = viewerWsMessages.find((message): message is Extract<WsMessage, { type: "clock" }> => message.type === "clock");
let frameIndex = 0;
let playing = true;
let speed = initialClock?.speed ?? 120;
let simTs = initialClock?.sim_ts ?? "2026-07-18T00:30:00Z";
let tickId = initialClock?.tick_id ?? 0;
let pausedReason: ClockState["paused_reason"] = null;
let slowedReason: ClockState["slowed_reason"] = null;
let timer: ReturnType<typeof setTimeout> | undefined;

const frameDelay = () => 60_000 / speed;
const clockState = (): ClockState => ({ playing, speed, sim_ts: simTs, tick_id: tickId, paused_reason: pausedReason, slowed_reason: slowedReason });

export function broadcastFixtureMessage(message: WsMessage) {
  for (const listener of listeners) listener(structuredClone(message));
}

const broadcastClock = () => broadcastFixtureMessage({ type: "clock", ...clockState() });

const stopTimer = () => {
  clearTimeout(timer);
  timer = undefined;
};

const schedule = () => {
  stopTimer();
  if (!playing || listeners.size === 0) return;
  timer = setTimeout(publishNext, frameDelay());
};

const publishNext = () => {
  if (frameIndex >= frames.length) {
    // End of the recording: the replay restarts from tick 0 and keeps playing, so the demo never stops.
    // Same frames every loop, so it stays deterministic. The chosen speed carries over.
    const loopSpeed = speed;
    resetPlayback(true);
    speed = loopSpeed;
    broadcastClock();
  }
  const frame = frames[frameIndex++];

  for (const original of frame) {
    let message = original;
    if (original.type === "tick" && original.data.lane === "with") {
      simTs = original.data.ts;
      tickId = original.data.hub.tick_id;
    } else if (original.type === "clock") {
      pausedReason = original.paused_reason;
      slowedReason = original.slowed_reason;
      message = { type: "clock", ...clockState() };
    }
    broadcastFixtureMessage(message);
  }
  schedule();
};

const resetPlayback = (autoplay: boolean) => {
  stopTimer();
  frameIndex = 0;
  playing = autoplay;
  speed = initialClock?.speed ?? 120;
  simTs = initialClock?.sim_ts ?? "2026-07-18T00:30:00Z";
  tickId = initialClock?.tick_id ?? 0;
  pausedReason = null;
  slowedReason = null;
};

/** Applies fixture-mode play/pause/reset to the actual WebSocket replay, not just its REST response. */
export function controlFixtureViewer(body: SimControlRequest): ClockState {
  if (body.action === "reset") {
    resetPlayback(false);
  } else {
    if (body.speed != null) speed = body.speed;
    playing = body.action === "play";
    if (!playing) stopTimer();
  }
  broadcastClock();
  schedule();
  return structuredClone(clockState());
}

/** Replays the shared viewer fixture in contract order and obeys fixture-mode simulation controls. */
export function subscribeFixtureViewer(
  onMessage: (message: WsMessage) => void,
  onStatus: (status: ConnectionStatus) => void,
): () => void {
  let stopped = false;
  onStatus("connecting");

  const start = setTimeout(() => {
    if (stopped) return;
    const firstListener = listeners.size === 0;
    listeners.add(onMessage);
    onStatus("open");
    if (firstListener) {
      resetPlayback(true);
      publishNext();
    } else {
      onMessage({ type: "clock", ...clockState() });
    }
  }, 20);

  return () => {
    stopped = true;
    clearTimeout(start);
    listeners.delete(onMessage);
    if (listeners.size === 0) stopTimer();
    onStatus("closed");
  };
}
