import type { Category, DecisionStatus, DeviceState, Importance, Lane } from "@/types";

/** Glow / accent per equipment category on the isometric floor. */
export const CATEGORY_ACCENT: Record<Category, string> = {
  cooking: "oklch(0.78 0.17 55)",
  refrigeration: "oklch(0.82 0.11 210)",
  water_heating: "oklch(0.75 0.13 245)",
  cooling: "oklch(0.86 0.1 195)",
  lighting: "oklch(0.9 0.13 90)",
  other: "oklch(0.8 0.06 290)",
};

/** One stable color per device (by its position in the kitchen), shared by the floor callouts and the donut. */
const DEVICE_PALETTE = [
  "oklch(0.76 0.17 152)",
  "oklch(0.72 0.15 250)",
  "oklch(0.8 0.15 75)",
  "oklch(0.7 0.17 25)",
  "oklch(0.72 0.15 300)",
  "oklch(0.8 0.12 200)",
  "oklch(0.75 0.16 350)",
  "oklch(0.84 0.16 125)",
  "oklch(0.76 0.16 50)",
  "oklch(0.74 0.12 175)",
  "oklch(0.66 0.15 275)",
  "oklch(0.88 0.13 95)",
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
  awaiting_approval: "needs approval",
  approved: "approved",
  declined: "declined",
  expired: "expired",
  undone: "undone",
};
