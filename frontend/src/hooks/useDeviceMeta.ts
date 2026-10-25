import { useMemo } from "react";
import {
  CookingPot,
  Droplets,
  Fan,
  Flame,
  Lightbulb,
  Plug,
  Refrigerator,
  Snowflake,
  WashingMachine,
  Wind,
  type LucideIcon,
} from "lucide-react";
import { deviceColor } from "@/lib/theme";
import { useDashboardStore as useSim } from "@/data";
import type { Category, Device } from "@/types";

export interface DeviceMeta {
  device: Device;
  category: Category;
  color: string;
  icon: LucideIcon;
  /** Job devices (dishwasher, ice machine) can be started by the owner. */
  isJob: boolean;
  minPowerPct: number | null;
}

const TYPE_ICON: Record<string, LucideIcon> = {
  hvac: Fan,
  walk_in_cooler: Snowflake,
  reach_in_fridge: Refrigerator,
  freezer: Snowflake,
  ice_machine: Snowflake,
  fryer: Flame,
  oven: CookingPot,
  grill: Flame,
  dishwasher: WashingMachine,
  water_heater: Droplets,
  lights: Lightbulb,
  kitchen_exhaust: Wind,
  other_equipment: Plug,
};

const CATEGORY_ICON: Record<Category, LucideIcon> = {
  cooking: Flame,
  refrigeration: Snowflake,
  water_heating: Droplets,
  cooling: Fan,
  lighting: Lightbulb,
  other: Plug,
};

// Used only until the catalog has loaded (or for a type the catalog doesn't list).
const FALLBACK_CATEGORY: Record<string, Category> = {
  hvac: "cooling",
  walk_in_cooler: "refrigeration",
  reach_in_fridge: "refrigeration",
  freezer: "refrigeration",
  ice_machine: "refrigeration",
  fryer: "cooking",
  oven: "cooking",
  grill: "cooking",
  dishwasher: "water_heating",
  water_heater: "water_heating",
  lights: "lighting",
  kitchen_exhaust: "other",
  other_equipment: "other",
};

/** Per-device display info: category (from the catalog), stable color, icon. In kitchen order. */
export function useDeviceMeta(): DeviceMeta[] {
  const kitchen = useSim((s) => s.kitchen);
  const catalog = useSim((s) => s.catalog);
  return useMemo(
    () =>
      (kitchen?.devices ?? []).map((device, i) => {
        const type = catalog?.find((t) => t.type_id === device.type_id);
        const category = type?.category ?? FALLBACK_CATEGORY[device.type_id] ?? "other";
        return {
          device,
          category,
          color: deviceColor(i),
          icon: TYPE_ICON[device.type_id] ?? CATEGORY_ICON[category],
          isJob: type ? type.power_model === "job" : device.importance === "deferrable",
          minPowerPct:
            type?.default_importance === "flexible" && "min_power_pct" in type.default_limits
              ? Number(type.default_limits.min_power_pct)
              : null,
        };
      }),
    [kitchen, catalog],
  );
}
