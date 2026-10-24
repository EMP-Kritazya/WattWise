import type { Category, DeviceState, Lane } from "@/types";
import type { FloorKind, PropKind } from "./plan";

// three.js needs plain hex colors (no oklch / CSS variables). These mirror the app theme in index.css.

export const BACKGROUND = "#0c1120";

export const FLOOR: Record<FloorKind, string> = {
  kitchen: "#394151",
  cold: "#33495c",
  dish: "#364152",
  office: "#34354d",
  dining: "#6a4730",
  pad: "#243029",
};

export const WALL = "#485068";
export const INNER_WALL = "#5a6382";

export const PROP: Record<PropKind, { color: string; metal?: number; rough?: number }> = {
  steel: { color: "#c3c9d2", metal: 0.65, rough: 0.32 },
  darkWood: { color: "#5b3c27", rough: 0.7 },
  wood: { color: "#8c5c36", rough: 0.65 },
  chair: { color: "#46301f", rough: 0.8 },
  pot: { color: "#8a5940", rough: 0.9 },
  leaves: { color: "#3d9a57", rough: 0.85 },
};

export const BODY = {
  steel: { color: "#c3c9d2", metal: 0.7, rough: 0.28 },
  white: { color: "#e1e7ee", metal: 0.1, rough: 0.45 },
  unit: { color: "#8f99a6", metal: 0.4, rough: 0.5 },
  dark: { color: "#1b202c", metal: 0.2, rough: 0.6 },
};

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
