import hostTakenFixture from "@fixtures/hub_protocol/hub_welcome_host_taken.json";
import type { HubToServerMessage, ServerToHubMessage, SimTickMessage } from "@/types";
import { hubServerMessages } from "./fixtures";

export interface MockHubConnection {
  send(message: HubToServerMessage): void;
  close(): void;
}

/**
 * In-browser /ws/hub fixture server. It emits the recorded build, then sends exactly one sim_tick at a time and waits for
 * a hub_report carrying the same tick_id before advancing.
 */
export function connectMockHubServer(
  onMessage: (message: ServerToHubMessage) => void,
  options: { hostTaken?: boolean; intervalMs?: number } = {},
): MockHubConnection {
  const welcome = hubServerMessages.find((message) => message.type === "hub_welcome");
  const build = hubServerMessages.find((message) => message.type === "sim_build");
  const ticks = hubServerMessages.filter((message): message is SimTickMessage => message.type === "sim_tick");
  const intervalMs = options.intervalMs ?? 500;
  let started = false;
  let closed = false;
  let waitingFor: number | null = null;
  let tickIndex = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const sendNextTick = () => {
    if (closed || waitingFor != null) return;
    const tick = ticks[tickIndex];
    if (!tick) return;
    waitingFor = tick.tick_id;
    onMessage(structuredClone(tick));
  };

  return {
    send(message) {
      if (closed) return;
      if (message.type === "hub_hello") {
        if (started) return;
        started = true;
        if (options.hostTaken) {
          onMessage(structuredClone(hostTakenFixture) as ServerToHubMessage);
          return;
        }
        if (welcome) onMessage(structuredClone(welcome));
        if (build) onMessage(structuredClone(build));
        timer = setTimeout(sendNextTick, 0);
        return;
      }
      if (message.type === "hub_report" && message.tick_id === waitingFor) {
        waitingFor = null;
        tickIndex += 1;
        timer = setTimeout(sendNextTick, intervalMs);
      }
    },
    close() {
      closed = true;
      clearTimeout(timer);
    },
  };
}
