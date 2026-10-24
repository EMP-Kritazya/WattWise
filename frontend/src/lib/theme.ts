import type { Category, DecisionStatus, DeviceState, Importance, Lane } from "@/types";

/** Glow / accent per equipment category on the isometric floor. */
export const CATEGORY_ACCENT: Record<Category, string> = {
  cooking: "#FFB4A2",
  refrigeration: "#A9D6F5",
  water_heating: "#FFC8DD",
  cooling: "#E9EDC9",
  lighting: "#FFB703",
  other: "#C3CEF6",
};

/** One stable color per device (by its position in the kitchen), shared by the floor callouts and the donut. */
const DEVICE_PALETTE = [
  "#2EC4B6",
  "#A9D6F5",
  "#FFB703",
  "#EF476F",
  "#C3CEF6",
  "#BDE0FE",
  "#FFC8DD",
  "#CDEAC0",
  "#FFB4A2",
  "#69C9BF",
  "#E5989B",
  "#FFD6A5",
];
export const deviceColor = (index: number) => DEVICE_PALETTE[index % DEVICE_PALETTE.length];

// Colors carry meaning (UI.md): always_on grey, flexible blue, deferrable amber; Without lane red, With lane green.
export const IMPORTANCE_LABEL: Record<Importance, string> = {
  always_on: "Always on",
  flexible: "Flexible",
  deferrable: "Deferrable",
};

export const IMPORTANCE_BADGE: Record<Importance, string> = {
  always_on: "border-transparent bg-importance-always-on/15 text-importance-always-on",
  flexible: "border-transparent bg-importance-flexible/15 text-importance-flexible",
  deferrable: "border-transparent bg-importance-deferrable/20 text-importance-deferrable",
};

export const LANE_LABEL: Record<Lane, string> = { without: "Without WattWise", with: "With WattWise" };
export const LANE_COLOR: Record<Lane, string> = { without: "var(--lane-without)", with: "var(--lane-with)" };

export const DEVICE_STATE_LABEL: Record<DeviceState, string> = {
  off: "off",
  on: "on",
  reduced: "reduced",
  waiting: "waiting",
  running_job: "running",
};

export const STATUS_LABEL: Record<DecisionStatus, string> = {
  executed: "done",
  undone: "undone",
};
