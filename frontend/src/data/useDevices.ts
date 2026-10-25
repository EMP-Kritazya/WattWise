import { useSyncExternalStore } from "react";
import { useLive } from "./useLive";
import type { Device, Lane } from "@/types";

const hostDevices: Record<Lane, Device[]> = { without: [], with: [] };
const hostListeners = new Set<() => void>();

/** The hub publishes its current appliance readings here; only the /sim host reads this side of the bridge. */
export function publishHostDevices(lane: Lane, devices: Device[]) {
  hostDevices[lane] = structuredClone(devices);
  hostListeners.forEach((listener) => listener());
}

const parsePhysical = (json: string | null): Device["physical"] => {
  if (!json) return undefined;
  try {
    return JSON.parse(json) as Device["physical"];
  } catch {
    return undefined;
  }
};

/** One device hook for both contexts: hub state on /sim, live_device rows in every viewer tab. */
export function useDevices(lane: Lane = "with"): Device[] {
  const viewerDevices = useLive((state) => state.live_device)
    .filter((row) => row.lane === lane)
    .map((row) => ({
      device_id: row.device_id,
      type_id: row.type_id,
      name: row.name,
      importance: row.importance,
      state: row.state,
      power_kw: row.power_kw,
      rated_kw: row.rated_kw,
      power_pct: row.power_pct,
      source: row.source,
      physical: parsePhysical(row.physical_json),
    }));
  const hosted = useSyncExternalStore(
    (listener) => {
      hostListeners.add(listener);
      return () => hostListeners.delete(listener);
    },
    () => hostDevices[lane],
  );
  return location.pathname === "/sim" ? hosted : viewerDevices;
}
