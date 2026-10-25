import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { WsMessage } from "@/types";
import { fixtureLiveRows } from "./liveRows";
import { controlFixtureViewer, subscribeFixtureViewer } from "./viewerWs";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("fixture simulation controls", () => {
  it("pauses and resumes the actual viewer message stream", () => {
    const received: WsMessage[] = [];
    const unsubscribe = subscribeFixtureViewer((message) => received.push(message), () => {});
    vi.advanceTimersByTime(20);
    vi.advanceTimersByTime(500);
    const tickAtPause = received.filter((message) => message.type === "tick").at(-1)?.data.hub.tick_id;

    const paused = controlFixtureViewer({ action: "pause" });
    expect(paused.playing).toBe(false);
    vi.advanceTimersByTime(5_000);
    expect(received.filter((message) => message.type === "tick").at(-1)?.data.hub.tick_id).toBe(tickAtPause);

    const resumed = controlFixtureViewer({ action: "play", speed: 120 });
    expect(resumed.playing).toBe(true);
    vi.advanceTimersByTime(500);
    expect(received.filter((message) => message.type === "tick").at(-1)?.data.hub.tick_id).toBe((tickAtPause ?? 0) + 1);

    const reset = controlFixtureViewer({ action: "reset" });
    expect(reset).toMatchObject({ playing: false, tick_id: 0, sim_ts: "2026-07-18T00:30:00Z" });
    unsubscribe();
  });

  it("freezes and resets the Spacetime-shaped fixture rows", () => {
    const stop = fixtureLiveRows.start();
    const beforePause = fixtureLiveRows.snapshot().live_tick[0]?.tick_id;
    fixtureLiveRows.control({ action: "pause" });
    vi.advanceTimersByTime(5_000);
    expect(fixtureLiveRows.snapshot().live_tick[0]?.tick_id).toBe(beforePause);

    fixtureLiveRows.control({ action: "play", speed: 120 });
    vi.advanceTimersByTime(500);
    expect(fixtureLiveRows.snapshot().live_tick[0]?.tick_id).toBe((beforePause ?? 0) + 1);

    const reset = fixtureLiveRows.control({ action: "reset" });
    expect(reset).toMatchObject({ playing: false, tick_id: 0, sim_ts: "2026-07-18T00:30:00Z" });
    expect(fixtureLiveRows.snapshot().live_tick).toEqual([]);
    stop();
  });

  it("publishes a surge request immediately while playback is paused", () => {
    fixtureLiveRows.control({ action: "reset" });
    let latest = fixtureLiveRows.snapshot();
    const unsubscribe = fixtureLiveRows.subscribe((tables) => {
      latest = tables;
    });

    fixtureLiveRows.requestSurge(40, 60);

    expect(latest.surge_request.at(-1)).toMatchObject({ customers: 40, duration_min: 60, consumed: false });
    unsubscribe();
  });
});
