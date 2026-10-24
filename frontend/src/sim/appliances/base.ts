import type { Command, CommandAck, Device, DevicePhysical, DeviceState, Lane } from "@/types";
import { clamp, round } from "@/sim/math";
import type { Appliance, ApplianceDefinition, ApplianceInputs } from "@/sim/types";

const minPowerPct = (limits: ApplianceDefinition["limits"]) =>
  "min_power_pct" in limits ? limits.min_power_pct : 0;

export abstract class BaseAppliance implements Appliance {
  readonly deviceId: string;
  readonly typeId: string;
  readonly ratedKw: number;
  protected readonly definition: ApplianceDefinition;
  protected enabled = true;
  protected reductionPct: number | null = null;
  protected powerKw = 0;
  protected state: DeviceState = "off";
  protected physical: DevicePhysical | undefined;

  constructor(definition: ApplianceDefinition) {
    this.definition = definition;
    this.deviceId = definition.device.device_id;
    this.typeId = definition.device.type_id;
    this.ratedKw = definition.device.rated_kw;
  }

  abstract step(minutes: number, inputs: ApplianceInputs): void;

  protected controlledPower(naturalKw: number) {
    if (!this.enabled) return 0;
    const requestedFraction = (this.reductionPct ?? 100) / 100;
    return round(clamp(naturalKw * requestedFraction, 0, this.ratedKw));
  }

  protected activeState(): DeviceState {
    if (!this.enabled) return "off";
    return this.reductionPct == null ? "on" : "reduced";
  }

  reading(): Device {
    return {
      ...this.definition.device,
      state: this.state,
      power_kw: round(this.powerKw),
      power_pct: this.ratedKw === 0 ? 0 : Math.round((this.powerKw / this.ratedKw) * 100),
      physical: this.physical == null ? undefined : structuredClone(this.physical),
    };
  }

  apply(command: Command, lane: Lane): CommandAck {
    const ack: CommandAck = {
      command_id: command.command_id,
      lane,
      ok: true,
      applied_value: command.value,
      reason: null,
    };

    if (command.action === "off") {
      if (!this.enabled) return { ...ack, ok: false, applied_value: null, reason: "already_off" };
      this.enabled = false;
      this.powerKw = 0;
      this.state = "off";
      return { ...ack, applied_value: null };
    }
    if (command.action === "on" || command.action === "start") {
      this.enabled = true;
      return { ...ack, applied_value: null };
    }
    if (command.action === "restore") {
      this.reductionPct = null;
      return { ...ack, applied_value: null };
    }
    if (command.action === "reduce") {
      const requested = command.value ?? 100;
      const applied = clamp(requested, minPowerPct(this.definition.limits), 100);
      this.reductionPct = applied;
      return {
        ...ack,
        applied_value: applied,
        reason: applied === requested ? null : "out_of_range",
      };
    }
    return { ...ack, ok: false, applied_value: null };
  }
}
