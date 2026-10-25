import type { Category, DeviceState, Lane } from "@/types";
import type { FloorKind, PropKind } from "./plan";

// three.js needs plain hex colors (no oklch / CSS variables). These mirror the app theme in index.css.

// Toy Box palette (frontend/UI_CONCEPTS.md): warm cream stage, pastel appliances, ink outlines.
export const BACKGROUND = "#FFF6E9";
export const INK = "#22223B";
export const SLAB = "#E8B89A";

/** Floor pattern per room: [pattern, colour A, colour B]. */
export const FLOOR: Record<FloorKind, ["checker" | "planks", string, string]> = {
  kitchen: ["checker", "#F7D9C4", "#F1C9AE"],
  cold: ["checker", "#DCEBF7", "#CDE0F1"],
  dish: ["checker", "#DDF2E3", "#CBE8D4"],
  office: ["checker", "#EADFF6", "#E2D4F2"],
  dining: ["planks", "#F3D3A6", "#E2BC88"],
  pad: ["checker", "#DCD6CE", "#D3CCC3"],
};

export const WALL = "#FFF1E2";
export const INNER_WALL = "#FFE7D1";
export const WINDOW = "#BFE3FF";

export const PROP: Record<PropKind, { color: string; metal?: number; rough?: number }> = {
  steel: { color: "#E9E4F0" },
  darkWood: { color: "#9C6644" },
  wood: { color: "#C98B5E" },
  chair: { color: "#F4A261" },
  pot: { color: "#D88C5A" },
  leaves: { color: "#8BC34A" },
};

/** One pastel per appliance type, so each is recognisable at a glance. */
export const APPLIANCE: Record<string, string> = {
  fryer: "#FFB4A2",
  grill: "#FFD6A5",
  oven: "#E5989B",
  reach_in_fridge: "#BDE0FE",
  walk_in_cooler: "#A9D6F5",
  freezer: "#C3CEF6",
  dishwasher: "#A2D2FF",
  water_heater: "#FFC8DD",
  ice_machine: "#CDEAC0",
  hvac: "#E9EDC9",
};
/** Fallback per category for types the catalog adds later. */
export const APPLIANCE_BY_CATEGORY: Record<Category, string> = {
  cooking: "#FFB4A2",
  refrigeration: "#BDE0FE",
  water_heating: "#FFC8DD",
  cooling: "#E9EDC9",
  lighting: "#FFE08A",
  other: "#E9E4F0",
};
/** Idle / off appliances fade toward this grey. */
export const OFF_TINT = "#D9D4CC";

/** Emissive glow per equipment category. */
export const ACCENT: Record<Category, string> = {
  cooking: "#ff7a1a",
  refrigeration: "#5ad1ff",
  water_heating: "#4c8dff",
  cooling: "#71e8ff",
  lighting: "#ffd27a",
  other: "#b48cff",
};

export const STATE_HEX: Record<DeviceState, string> = {
  on: "#34d399",
  running_job: "#34d399",
  reduced: "#6b8cff",
  waiting: "#fbbf24",
  off: "#4b5563",
};

export const LANE_HEX: Record<Lane, string> = { without: "#f87171", with: "#34d399" };

export const SHIRTS = ["#5b8def", "#ef6b5b", "#f2c94c", "#4fb38a", "#a77bdb", "#d9dde6", "#ef8fb6", "#57c7d4"];
export const SKIN = ["#f1c9a5", "#c98e63", "#8d5a3b", "#f6dcc3", "#a8714d"];
