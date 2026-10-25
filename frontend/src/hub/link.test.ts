import { afterEach, expect, it, vi } from "vitest";
import fixture from "@fixtures/hub_protocol/server_to_hub.jsonl?raw";
import { HubLink } from "./link";

class Socket {
  static instances: Socket[] = [];
  sent: unknown[] = [];
  handlers = new Map<string, ((event: { data?: string }) => void)[]>();
  constructor(_url: string) { Socket.instances.push(this); }
  addEventListener(name: string, fn: (event: { data?: string }) => void) {
    this.handlers.set(name, [...(this.handlers.get(name) ?? []), fn]);
  }
  emit(name: string, event = {}) { this.handlers.get(name)?.forEach(fn => fn(event)); }
  send(message: string) { this.sent.push(JSON.parse(message)); }
  close() { this.emit("close"); }
  receive(message: unknown) { this.emit("message", { data: JSON.stringify(message) }); }
}

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); Socket.instances = []; });

it("reconnects on disconnect and cancels reconnect when the host is closed", () => {
  vi.useFakeTimers(); vi.stubGlobal("WebSocket", Socket);
  const link = new HubLink(); link.connect("ws://local/ws/hub");
  Socket.instances[0].emit("close");
  vi.advanceTimersByTime(1000);
  expect(Socket.instances).toHaveLength(2);
  link.close(); vi.advanceTimersByTime(2000);
  expect(Socket.instances).toHaveLength(2);
});

it("answers only the final replay tick before resuming live reports", () => {
  vi.stubGlobal("WebSocket", Socket);
  const messages = fixture.trim().split("\n").map(line => JSON.parse(line));
  const link = new HubLink(); link.connect("ws://local/ws/hub");
  const socket = Socket.instances[0];
  socket.receive({ type: "hub_welcome", accepted: true, reason: null, tick_id: 2 });
  socket.receive(messages.find(m => m.type === "sim_build"));
  const ticks = messages.filter(m => m.type === "sim_tick");
  socket.receive({ ...ticks[0], replay: true });
  expect(socket.sent).toHaveLength(0);
  socket.receive({ ...ticks[1], replay: true });
  expect(socket.sent).toHaveLength(1);
  expect(socket.sent[0]).toMatchObject({ type: "hub_report", tick_id: 2 });
  socket.receive(ticks[2]);
  expect(socket.sent).toHaveLength(2);
  link.close();
});
