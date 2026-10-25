import { describe, expect, it } from "vitest";
import protocolFixture from "@fixtures/hub_protocol/server_to_hub.jsonl?raw";
import type { Command, HubReportMessage, ServerToHubMessage, SimBuildMessage, SimTickMessage } from "@/types";
import { round } from "@/sim/math";
import { BrowserHub } from "./hub";

const messages = protocolFixture
  .trim()
  .split("\n")
  .map((line) => JSON.parse(line) as ServerToHubMessage);
const build = messages.find((message): message is SimBuildMessage => message.type === "sim_build");
const ticks = messages.filter((message): message is SimTickMessage => message.type === "sim_tick");

if (!build) throw new Error("Fixture is missing sim_build");

const runFixture = () => {
  const hub = new BrowserHub();
  hub.build(build);
  return ticks.map((tick) => hub.tick(tick));
};

const command = (partial: Partial<Command> & Pick<Command, "command_id" | "device_id" | "action">): Command => ({
  lane: "with",
  ts: "2026-07-18T00:30:00Z",
  value: null,
  decision_id: null,
  issued_by: "engine",
  ...partial,
});

const tickWith = (tickId: number, commands: Command[]): SimTickMessage => ({
  type: "sim_tick",
  tick_id: tickId,
  sim_ts: `2026-07-18T00:${String(29 + tickId).padStart(2, "0")}:00Z`,
  minutes: 1,
  surges: [],
  inputs: { outdoor_temp_c: 29, crowd_multiplier: 1.25, is_open: true },
  commands,
  replay: false,
});

describe("BrowserHub fixture protocol", () => {
  it("runs all 120 recorded ticks byte-identically", () => {
    expect(ticks).toHaveLength(120);
    expect(JSON.stringify(runFixture())).toBe(JSON.stringify(runFixture()));
  });

  it("keeps every report internally consistent and contract-shaped", () => {
    const reports = runFixture();
    for (const message of reports) {
      expect(message.type).toBe("hub_report");
      for (const lane of ["without", "with"] as const) {
        const report = message.reports[lane];
        expect(report).toMatchObject({
          hub_id: "sim_hub",
          lane,
          tick_id: message.tick_id,
          source: "simulated",
        });
        expect(report.total_kw).toBe(round(report.devices.reduce((sum, device) => sum + device.power_kw, 0)));
        expect(new Set(report.devices.map((device) => device.device_id)).size).toBe(report.devices.length);
        for (const device of report.devices) {
          expect(device.power_kw).toBeGreaterThanOrEqual(0);
          expect(device.power_kw).toBeLessThanOrEqual(device.rated_kw);
          expect(device.power_pct).toBeGreaterThanOrEqual(0);
          expect(device.power_pct).toBeLessThanOrEqual(100);
        }
      }
      const sourceTick = ticks[message.tick_id - 1];
      expect(message.reports.without.acks.length + message.reports.with.acks.length).toBe(sourceTick?.commands.length);
    }
  });

  it("clamps reductions to physical limits and only changes the commanded lane", () => {
    const hub = new BrowserHub();
    hub.build(build);
    const report = hub.tick(tickWith(1, [command({ command_id: "reduce", device_id: "hvac_1", action: "reduce", value: 20 })]));
    const ack = report.reports.with.acks[0];
    expect(ack).toMatchObject({ ok: true, applied_value: 40, reason: "out_of_range" });
    const baseline = report.reports.without.devices.find((device) => device.device_id === "hvac_1");
    const reduced = report.reports.with.devices.find((device) => device.device_id === "hvac_1");
    expect(reduced?.state).toBe("reduced");
    expect(reduced?.power_kw).toBe(round((baseline?.power_kw ?? 0) * 0.4));
  });

  it("acknowledges delay bounds, running-job rejection, unknown devices, and already-off", () => {
    const hub = new BrowserHub();
    hub.build(build);
    const first = hub.tick(tickWith(1, [
      command({ command_id: "delay", device_id: "dishwasher_1", action: "delay", value: 999 }),
      command({ command_id: "missing", device_id: "no_such_device", action: "off" }),
      command({ command_id: "off", device_id: "lights_1", action: "off" }),
      command({ command_id: "off_again", device_id: "lights_1", action: "off" }),
    ]));
    expect(first.reports.with.acks).toEqual(expect.arrayContaining([
      expect.objectContaining({ command_id: "delay", ok: true, applied_value: 60, reason: "out_of_range" }),
      expect.objectContaining({ command_id: "missing", ok: false, reason: "unknown_device" }),
      expect.objectContaining({ command_id: "off_again", ok: false, reason: "already_off" }),
    ]));

    const running = hub.tick(tickWith(2, [
      command({ command_id: "start", device_id: "ice_machine_1", action: "start" }),
      command({ command_id: "delay_running", device_id: "ice_machine_1", action: "delay", value: 10 }),
    ]));
    expect(running.reports.with.acks[1]).toMatchObject({ ok: false, applied_value: null, reason: "job_running" });
    expect(running.reports.with.devices.find((device) => device.device_id === "ice_machine_1")?.state).toBe("running_job");
  });
});

describe("HubReportMessage type boundary", () => {
  it("returns both lanes", () => {
    const report: HubReportMessage = runFixture()[0]!;
    expect(Object.keys(report.reports).sort()).toEqual(["with", "without"]);
  });
});
