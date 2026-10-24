// STUB: proposed eval artifact shape for the Evaluation Lab (docs/Claude_EVAL.md §11). Not in CONTRACTS.md yet;
// Kritazya owns the real shape (PLAN.md §7, Q8). Replace with generated types once the eval runner publishes artifacts.

export type EvalVerdict = "pass" | "fail";
/** Where the artifact came from. Only `simulated` may ever come from a real eval run; nothing here is `measured`. */
export type EvalSource = "illustrative_stub" | "simulated";
export type EvalStrategyKind = "baseline" | "fixed_rule" | "hvac_only" | "wattwise" | "oracle";
export type EvalSplit = "dev" | "held_out";

/** One precomputed eval run: every scenario × strategy, computed by the eval runner (never the browser). */
export interface EvalArtifact {
  run_id: string;
  source: EvalSource;
  generated_at: string;
  provenance: EvalProvenance;
  scenarios: EvalScenario[];
  strategies: EvalStrategy[];
  hard_constraints: EvalConstraint[];
  results: EvalResult[];
}

export interface EvalProvenance {
  engine_version: string;
  plant: string;
  tariff_id: string;
  tariff_label: string;
  seeds: number[];
  note: string;
}

export interface EvalScenario {
  scenario_id: string;
  name: string;
  summary: string;
  weather_label: string;
  traffic_label: string;
  outdoor_max_c: number;
  peak_cap_kw: number;
  split: EvalSplit;
}

export interface EvalStrategy {
  strategy_id: string;
  name: string;
  kind: EvalStrategyKind;
  /** False for diagnostic ablations and the oracle: never shown as a deployable winner. */
  deployable: boolean;
  summary: string;
}

export interface EvalConstraint {
  constraint_id: string;
  label: string;
}

export interface EvalResult {
  scenario_id: string;
  strategy_id: string;
  /** `fail` whenever any hard constraint has a violation, regardless of cost (set by the eval runner). */
  verdict: EvalVerdict;
  bill: { energy_usd: number; demand_usd: number; total_usd: number };
  /** Versus the unoptimized baseline in the same scenario; null for the baseline itself. */
  savings_usd: number | null;
  peak_demand_kw: number;
  peak_avoided_kw: number | null;
  comfort: { max_indoor_temp_c: number; degree_minutes_above: number; minutes_outside_band_min: number };
  violations: { constraint_id: string; count: number }[];
  operations: { commands: number; escalations: number; unmet_kwh: number };
  /** Completed, locally aligned 15-minute blocks. */
  demand_blocks: { block_start_ts: string; demand_kw: number }[];
  /** One representative decision from this run, for the trace card. */
  trace: EvalTraceItem | null;
}

export interface EvalTraceItem {
  ts: string;
  device_name: string;
  action: string;
  reason: string;
  peak_before_kw: number;
  peak_after_kw: number;
}
