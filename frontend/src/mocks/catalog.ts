import type { EquipmentType, ImportanceLimits } from "@/types";

// MOCK: the type list follows docs/design/SIMULATION.md; the kW figures are invented placeholders.
// The real catalog comes from the engine's backend/data/equipment_catalog.json via GET /api/catalog.
const NOTE = "MOCK placeholder, not a measured value";

const rows: EquipmentType[] = [
  { type_id: "hvac", name: "HVAC", category: "cooling", default_importance: "flexible", rated_kw: 12, min_power_pct: 40, power_model: "thermal", params: {}, source_note: NOTE },
  { type_id: "walk_in_cooler", name: "Walk-in cooler", category: "refrigeration", default_importance: "flexible", rated_kw: 3.5, min_power_pct: 50, power_model: "cycling", params: {}, source_note: NOTE },
  { type_id: "reach_in_fridge", name: "Reach-in fridge", category: "refrigeration", default_importance: "always_on", rated_kw: 0.8, min_power_pct: null, power_model: "cycling", params: {}, source_note: NOTE },
  { type_id: "freezer", name: "Freezer", category: "refrigeration", default_importance: "always_on", rated_kw: 1.2, min_power_pct: null, power_model: "cycling", params: {}, source_note: NOTE },
  { type_id: "ice_machine", name: "Ice machine", category: "refrigeration", default_importance: "deferrable", rated_kw: 1.5, min_power_pct: null, power_model: "job", params: { cycle_min: 20 }, source_note: NOTE },
  { type_id: "fryer", name: "Fryer", category: "cooking", default_importance: "always_on", rated_kw: 14, min_power_pct: null, power_model: "demand_driven", params: {}, source_note: NOTE },
  { type_id: "oven", name: "Oven", category: "cooking", default_importance: "always_on", rated_kw: 10, min_power_pct: null, power_model: "demand_driven", params: {}, source_note: NOTE },
  { type_id: "grill", name: "Grill", category: "cooking", default_importance: "always_on", rated_kw: 9, min_power_pct: null, power_model: "demand_driven", params: {}, source_note: NOTE },
  { type_id: "dishwasher", name: "Dishwasher", category: "water_heating", default_importance: "deferrable", rated_kw: 6, min_power_pct: null, power_model: "job", params: { cycle_min: 30 }, source_note: NOTE },
  { type_id: "water_heater", name: "Water heater", category: "water_heating", default_importance: "flexible", rated_kw: 9, min_power_pct: 40, power_model: "cycling", params: {}, source_note: NOTE },
  { type_id: "lights", name: "Lights", category: "lighting", default_importance: "always_on", rated_kw: 3, min_power_pct: null, power_model: "fixed", params: {}, source_note: NOTE },
];

// default_limits as in equipment_catalog.json: flexible keeps its min power, deferrable must finish before close.
const DEFAULT_FINISH: Record<string, string> = { dishwasher: "21:30", ice_machine: "21:00" };
const limitsFor = (t: EquipmentType): ImportanceLimits =>
  t.default_importance === "flexible"
    ? { min_power_pct: t.min_power_pct ?? 40, max_reduce_min: 30 }
    : t.default_importance === "deferrable"
      ? { max_delay_min: 60, must_finish_by: DEFAULT_FINISH[t.type_id] ?? "21:30" }
      : {};
export const mockCatalog: EquipmentType[] = rows.map((t) => ({ ...t, default_limits: limitsFor(t) }));
