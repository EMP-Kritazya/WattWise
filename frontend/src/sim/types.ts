import type { Command, CommandAck, Device, EquipmentType, ImportanceLimits, Lane, SimInputs } from "@/types";

export interface CustomerSnapshot {
  arrivals: number;
  customersPerHour: number;
  ordersInProgress: number;
}

export interface ApplianceInputs extends SimInputs, CustomerSnapshot {
  indoorTempC: number;
}

export interface Appliance {
  readonly deviceId: string;
  readonly typeId: string;
  readonly ratedKw: number;
  step(minutes: number, inputs: ApplianceInputs): void;
  reading(): Device;
  apply(command: Command, lane: Lane): CommandAck;
  setIndoorTemp?(temperatureC: number): void;
}

export interface ApplianceDefinition {
  device: Device;
  equipment: EquipmentType;
  limits: ImportanceLimits;
}
