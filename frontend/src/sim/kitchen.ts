import type { Command, CommandAck, Device, EquipmentEntry, EquipmentType, Lane, SimInputs } from "@/types";
import { createAppliance } from "@/sim/appliances";
import { clamp, round } from "@/sim/math";
import { createKitchenStore, type KitchenStore } from "@/sim/store";
import type { Appliance, CustomerSnapshot } from "@/sim/types";

const limitsFor = (typeId: string, entries: EquipmentEntry[]) =>
  entries.find((entry) => entry.type_id === typeId)?.limits ?? {};

export class KitchenSimulation {
  readonly store: KitchenStore;
  private readonly appliances: Appliance[];
  private readonly applianceById: Map<string, Appliance>;
  private indoorTempC = 22.5;

  constructor(devices: Device[], catalog: EquipmentType[], entries: EquipmentEntry[]) {
    const catalogById = new Map(catalog.map((item) => [item.type_id, item]));
    this.appliances = devices.map((device) => {
      const equipment = catalogById.get(device.type_id);
      if (!equipment) throw new Error(`Unknown equipment type: ${device.type_id}`);
      return createAppliance({ device, equipment, limits: limitsFor(device.type_id, entries) });
    });
    this.applianceById = new Map(this.appliances.map((appliance) => [appliance.deviceId, appliance]));
    this.store = createKitchenStore(devices);
  }

  apply(command: Command, lane: Lane): CommandAck {
    const appliance = this.applianceById.get(command.device_id);
    if (!appliance) {
      return {
        command_id: command.command_id,
        lane,
        ok: false,
        applied_value: null,
        reason: "unknown_device",
      };
    }
    const ack = appliance.apply(command, lane);
    this.publish();
    return ack;
  }

  step(minutes: number, inputs: SimInputs, customers: CustomerSnapshot) {
    const applianceInputs = { ...inputs, ...customers, indoorTempC: this.indoorTempC };
    this.appliances.forEach((appliance) => appliance.step(minutes, applianceInputs));

    const hvacKw = this.appliances
      .filter((appliance) => appliance.typeId === "hvac")
      .reduce((sum, appliance) => sum + appliance.reading().power_kw, 0);
    const outdoor = inputs.outdoor_temp_c ?? this.indoorTempC;
    const envelopeGain = (outdoor - this.indoorTempC) * 0.008;
    const peopleGain = customers.ordersInProgress * 0.0015;
    const cooling = hvacKw * 0.006;
    this.indoorTempC = clamp(this.indoorTempC + minutes * (envelopeGain + peopleGain - cooling), 17, 32);
    this.appliances.forEach((appliance) => appliance.setIndoorTemp?.(this.indoorTempC));
    this.publish();
  }

  readings() {
    return structuredClone(this.store.getState().devices);
  }

  private publish() {
    const devices = this.appliances.map((appliance) => appliance.reading());
    this.store.setState({ devices, indoorTempC: round(this.indoorTempC, 1) });
  }
}
