import { clamp, round } from "@/sim/math";
import type { ApplianceInputs } from "@/sim/types";
import { BaseAppliance } from "./base";

export class ThermalAppliance extends BaseAppliance {
  step(_minutes: number, inputs: ApplianceInputs) {
    const { setpoint_c: setpoint } = this.definition.equipment.params as { setpoint_c: number };
    const outdoorLoad = Math.max(0, (inputs.outdoor_temp_c ?? setpoint) - setpoint) * 0.045;
    const roomLoad = Math.max(0, inputs.indoorTempC - setpoint) * 0.5;
    const crowdLoad = inputs.ordersInProgress * 0.012;
    const natural = this.ratedKw * clamp(0.24 + outdoorLoad + roomLoad + crowdLoad, 0, 1);
    this.powerKw = inputs.is_open ? this.controlledPower(natural) : 0;
    this.state = inputs.is_open ? this.activeState() : "off";
    this.physical = { indoor_temp_c: round(inputs.indoorTempC, 1) };
  }

  setIndoorTemp(temperatureC: number) {
    this.physical = { indoor_temp_c: round(temperatureC, 1) };
  }
}
