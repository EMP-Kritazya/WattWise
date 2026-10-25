import { clamp, round } from "@/sim/math";
import type { ApplianceInputs } from "@/sim/types";
import { BaseAppliance } from "./base";

export class CyclingAppliance extends BaseAppliance {
  private phase: number;
  private temperatureC: number;

  constructor(...args: ConstructorParameters<typeof BaseAppliance>) {
    super(...args);
    this.phase = [...this.deviceId].reduce((sum, char) => sum + char.charCodeAt(0), 0) % 100;
    this.temperatureC = this.typeId === "freezer" ? -18 : this.typeId === "water_heater" ? 61 : 3.5;
  }

  step(minutes: number, inputs: ApplianceInputs) {
    const params = this.definition.equipment.params as { duty_idle_pct: number; duty_busy_pct: number };
    const duty = inputs.is_open
      ? params.duty_idle_pct + (params.duty_busy_pct - params.duty_idle_pct) * clamp(inputs.ordersInProgress / 22, 0, 1)
      : 0;
    this.phase = (this.phase + duty * minutes) % 100;
    const compressorOn = inputs.is_open && this.phase < duty;
    this.powerKw = compressorOn ? this.controlledPower(this.ratedKw) : 0;
    this.state = inputs.is_open ? this.activeState() : "off";

    const target = this.typeId === "freezer" ? -18 : this.typeId === "water_heater" ? 61 : 3.5;
    const drift = this.typeId === "water_heater" ? -0.07 : 0.045;
    const activeChange = this.typeId === "water_heater" ? 0.22 : -0.16;
    this.temperatureC += minutes * (compressorOn ? activeChange : drift + inputs.ordersInProgress * 0.0008);
    const bounds = this.typeId === "freezer" ? [-22, -12] : this.typeId === "water_heater" ? [48, 66] : [1, 10];
    this.temperatureC = clamp(this.temperatureC + (target - this.temperatureC) * 0.015, bounds[0], bounds[1]);
    this.physical = { box_temp_c: round(this.temperatureC, 1) };
  }
}
