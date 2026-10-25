import type { Appliance, ApplianceDefinition } from "@/sim/types";
import { CyclingAppliance } from "./cycling";
import { DemandAppliance } from "./demand";
import { FixedAppliance } from "./fixed";
import { JobAppliance } from "./job";
import { ThermalAppliance } from "./thermal";

export function createAppliance(definition: ApplianceDefinition): Appliance {
  switch (definition.equipment.power_model) {
    case "fixed": return new FixedAppliance(definition);
    case "cycling": return new CyclingAppliance(definition);
    case "thermal": return new ThermalAppliance(definition);
    case "demand_driven": return new DemandAppliance(definition);
    case "job": return new JobAppliance(definition);
  }
}

export { JobAppliance } from "./job";
