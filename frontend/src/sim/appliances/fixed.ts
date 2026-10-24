import { BaseAppliance } from "./base";
import type { ApplianceInputs } from "@/sim/types";

export class FixedAppliance extends BaseAppliance {
  step(_minutes: number, inputs: ApplianceInputs) {
    this.powerKw = inputs.is_open ? this.controlledPower(this.ratedKw) : 0;
    this.state = inputs.is_open ? this.activeState() : "off";
  }
}
