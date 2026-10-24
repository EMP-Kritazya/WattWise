import { useMemo } from "react";
import { useSim } from "@/store/sim";

/** device_id → display name ("HVAC 1"), from the kitchen the API returned. */
export function useDeviceNames(): Record<string, string> {
  const devices = useSim((s) => s.kitchen?.devices);
  return useMemo(() => Object.fromEntries((devices ?? []).map((d) => [d.device_id, d.name])), [devices]);
}
