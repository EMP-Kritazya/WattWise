import { afterEach, expect, it, vi } from "vitest";
import { realTransport } from "./real";

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); MockSocket.instances = []; });

it("keeps health available while removing owner escalation resolution", async () => {
  const health = { status: "ok", engine: "ready" };
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(health)));
  vi.stubGlobal("fetch", fetchMock);
  expect(await realTransport.health()).toEqual(health);
  expect(fetchMock).toHaveBeenCalledWith("/api/health", { method: "GET", headers: undefined, body: undefined });
  expect(realTransport).not.toHaveProperty("resolveEscalation");
});


class MockSocket {
  static OPEN = 1;
  static instances: MockSocket[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  close = vi.fn(() => { this.readyState = 3; this.onclose?.(); });
  readonly url: string;
  constructor(url: string) { this.url = url; MockSocket.instances.push(this); }
  open() { this.readyState = 1; this.onopen?.(); }
}

function sockets() {
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", MockSocket);
  vi.stubGlobal("location", { protocol: "http:", host: "localhost:5174" });
}

it("does not open a socket for StrictMode's discarded first effect", () => {
  sockets();
  const discard = realTransport.subscribe(vi.fn(), vi.fn());
  discard();
  const stop = realTransport.subscribe(vi.fn(), vi.fn());
  vi.runOnlyPendingTimers();
  expect(MockSocket.instances).toHaveLength(1);
  expect(MockSocket.instances[0].url).toBe("ws://localhost:5174/ws");
  MockSocket.instances[0].open();
  stop();
  expect(MockSocket.instances[0].close).toHaveBeenCalledOnce();
});

it("lets an in-flight handshake finish before closing and ignores late events", () => {
  sockets();
  const message = vi.fn(), status = vi.fn();
  const stop = realTransport.subscribe(message, status);
  vi.runOnlyPendingTimers();
  const socket = MockSocket.instances[0];
  stop();
  expect(socket.close).not.toHaveBeenCalled();
  socket.open();
  socket.onmessage?.({ data: '{"type":"chat_done","chat_id":"stale"}' });
  expect(socket.close).toHaveBeenCalledOnce();
  expect(message).not.toHaveBeenCalled();
  expect(status.mock.calls).toEqual([["connecting"]]);
  vi.runOnlyPendingTimers();
  expect(MockSocket.instances).toHaveLength(1);
});

it("reconnects after an unexpected disconnection", () => {
  sockets();
  const status = vi.fn();
  const stop = realTransport.subscribe(vi.fn(), status);
  vi.runOnlyPendingTimers();
  MockSocket.instances[0].open();
  MockSocket.instances[0].onclose?.();
  vi.advanceTimersByTime(500);
  expect(MockSocket.instances).toHaveLength(2);
  expect(status.mock.calls).toEqual([["connecting"], ["open"], ["closed"], ["connecting"]]);
  stop();
  MockSocket.instances[1].open();
});
