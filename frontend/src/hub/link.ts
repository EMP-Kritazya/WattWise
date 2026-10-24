import type {
  HubHelloMessage,
  HubToServerMessage,
  ServerToHubMessage,
  SimControlMessage,
} from "@/types";
import { publishHostDevices } from "@/data/useDevices";
import { BrowserHub } from "./hub";
import { useHubStatus } from "./status";

interface HubConnection {
  send(message: HubToServerMessage): void;
  close(): void;
}

const HELLO: HubHelloMessage = {
  type: "hub_hello",
  protocol: 1,
  hub_id: "sim_hub",
  role: "sim_host",
  client: "wattwise-web/0.1",
};

export class HubLink {
  private readonly hub = new BrowserHub();
  private connection: HubConnection | null = null;
  private connectionVersion = 0;

  async connectMock(options: { hostTaken?: boolean; intervalMs?: number } = {}) {
    this.close();
    const version = this.connectionVersion;
    this.setConnecting("Connecting to fixture hub…");
    const { connectMockHubServer } = await import("@/mocks/mockHubServer");
    if (version !== this.connectionVersion) return;
    const mock = connectMockHubServer((message) => this.handle(message), options);
    this.connection = mock;
    mock.send(HELLO);
  }

  connect(url = this.defaultUrl()) {
    this.close();
    this.setConnecting("Connecting to FastAPI…");
    const socket = new WebSocket(url);
    this.connection = {
      send: (message) => socket.send(JSON.stringify(message)),
      close: () => socket.close(),
    };
    socket.addEventListener("open", () => socket.send(JSON.stringify(HELLO)));
    socket.addEventListener("message", (event) => {
      try {
        this.handle(JSON.parse(String(event.data)) as ServerToHubMessage);
      } catch {
        useHubStatus.setState({ connection: "error", message: "Hub sent an unreadable message" });
      }
    });
    socket.addEventListener("error", () => {
      useHubStatus.setState({ connection: "error", message: "Could not reach /ws/hub" });
    });
    socket.addEventListener("close", () => {
      if (useHubStatus.getState().connection !== "host_taken") {
        useHubStatus.setState({ connection: "offline", message: "Simulation host disconnected", playing: false });
      }
    });
  }

  close() {
    this.connectionVersion += 1;
    this.connection?.close();
    this.connection = null;
  }

  private handle(message: ServerToHubMessage) {
    if (message.type === "hub_welcome") {
      if (!message.accepted) {
        useHubStatus.setState({
          connection: "host_taken",
          message: "Another browser is already the simulation host",
          tickId: message.tick_id,
        });
        return;
      }
      useHubStatus.setState({ connection: "connected", message: "Connected; waiting for kitchen build", tickId: message.tick_id });
      return;
    }
    if (message.type === "sim_build") {
      this.hub.build(message);
      useHubStatus.setState({ connection: "connected", message: `Hosting ${message.config.name}`, simTs: message.start_sim_ts });
      return;
    }
    if (message.type === "sim_control") {
      this.applyControl(message);
      return;
    }

    try {
      const report = this.hub.tick(message);
      publishHostDevices("without", report.reports.without.devices);
      publishHostDevices("with", report.reports.with.devices);
      useHubStatus.setState({
        connection: "connected",
        message: message.replay ? "Replaying recorded ticks" : "Simulation is live",
        tickId: report.tick_id,
        simTs: report.reports.with.ts,
        lastReport: report,
      });
      this.connection?.send(report);
    } catch (error) {
      useHubStatus.setState({
        connection: "error",
        message: error instanceof Error ? error.message : "Simulation tick failed",
      });
    }
  }

  private applyControl(message: SimControlMessage) {
    if (message.action === "reset") this.hub.reset();
    useHubStatus.setState({
      playing: message.action === "play",
      speed: message.speed,
      pausedReason: message.paused_reason,
      message: message.action === "play" ? `Running at ${message.speed}×` : message.action === "reset" ? "Simulation reset" : "Simulation paused",
    });
  }

  private setConnecting(message: string) {
    useHubStatus.setState({ connection: "connecting", message, lastReport: null, tickId: 0 });
  }

  private defaultUrl() {
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${location.host}/ws/hub`;
  }
}
