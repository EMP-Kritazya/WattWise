import type {
  CommandAck,
  HubReport,
  HubReportMessage,
  Lane,
  SimBuildMessage,
  SimTickMessage,
} from "@/types";
import { CustomerFlow, KitchenSimulation } from "@/sim";
import { addMinutes, round } from "@/sim/math";

const LANES: Lane[] = ["without", "with"];

/** Pure protocol-facing hub: build once, consume ticks, emit one report for each lane. */
export class BrowserHub {
  private buildMessage: SimBuildMessage | null = null;
  private customers: CustomerFlow | null = null;
  private kitchens: Record<Lane, KitchenSimulation> | null = null;

  build(message: SimBuildMessage) {
    this.buildMessage = structuredClone(message);
    this.customers = new CustomerFlow(message.seed);
    this.kitchens = {
      without: new KitchenSimulation(message.devices, message.catalog, message.config.equipment),
      with: new KitchenSimulation(message.devices, message.catalog, message.config.equipment),
    };
  }

  reset() {
    if (this.buildMessage) this.build(this.buildMessage);
  }

  tick(message: SimTickMessage): HubReportMessage {
    if (!this.kitchens || !this.customers) throw new Error("sim_tick received before sim_build");

    const acks: Record<Lane, CommandAck[]> = { without: [], with: [] };
    for (const command of message.commands) {
      acks[command.lane].push(this.kitchens[command.lane].apply(command, command.lane));
    }

    const customerSnapshot = this.customers.step(message.minutes, message.inputs, message.surges);
    for (const lane of LANES) {
      this.kitchens[lane].step(message.minutes, message.inputs, customerSnapshot);
    }

    const reports = {} as Record<Lane, HubReport>;
    for (const lane of LANES) {
      const devices = this.kitchens[lane].readings();
      reports[lane] = {
        hub_id: "sim_hub",
        lane,
        tick_id: message.tick_id,
        ts: addMinutes(message.sim_ts, message.minutes),
        total_kw: round(devices.reduce((sum, device) => sum + device.power_kw, 0)),
        customers_per_hour: customerSnapshot.customersPerHour,
        devices,
        acks: acks[lane],
        source: "simulated",
      };
    }
    return { type: "hub_report", tick_id: message.tick_id, reports };
  }
}
