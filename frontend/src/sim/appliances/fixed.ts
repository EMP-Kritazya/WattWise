import { BaseAppliance } from "./base";
import type { ApplianceInputs } from "@/sim/types";

export class FixedAppliance extends BaseAppliance {
  step(_minutes: number, inputs: ApplianceInputs) {
    // Ventilation (category "other", e.g. kitchen_exhaust) runs around the clock; lights run during opening hours.
    const on = inputs.is_open || this.definition.equipment.category === "other";
    this.powerKw = on ? this.controlledPower(this.ratedKw) : 0;
    this.state = on ? this.activeState() : "off";
  }
}
