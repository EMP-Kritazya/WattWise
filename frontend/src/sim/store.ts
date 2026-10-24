import { createStore, type StoreApi } from "zustand/vanilla";
import type { Device } from "@/types";

export interface KitchenStoreState {
  devices: Device[];
  indoorTempC: number;
}

export type KitchenStore = StoreApi<KitchenStoreState>;

export const createKitchenStore = (devices: Device[]): KitchenStore =>
  createStore<KitchenStoreState>(() => ({ devices: structuredClone(devices), indoorTempC: 22.5 }));
