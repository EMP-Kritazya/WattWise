import { clamp, round } from "@/sim/math";
import type { ApplianceInputs } from "@/sim/types";
import { BaseAppliance } from "./base";

export class DemandAppliance extends BaseAppliance {
  step(_minutes: number, inputs: ApplianceInputs) {
    const params = this.definition.equipment.params as { idle_kw: number; kw_per_order: number };
    const natural = clamp(params.idle_kw + params.kw_per_order * inputs.ordersInProgress, 0, this.ratedKw);
    this.powerKw = inputs.is_open ? this.controlledPower(natural) : 0;
    this.state = inputs.is_open ? this.activeState() : "off";
    this.physical = { orders_in_progress: Math.round(inputs.ordersInProgress) };
    this.powerKw = round(this.powerKw);
  }
}
