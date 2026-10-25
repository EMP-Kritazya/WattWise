// Contract shapes (CONTRACTS.md §1) as Convex validators, shared by schema.ts and the functions.
// Flat shapes are typed field by field; deep engine-owned blobs (KitchenConfig, Escalation options, Context sections,
// Proposal payloads) are stored as given (`v.any()`), since their structure belongs to the engine and the API models.

import { v } from "convex/values";

const nullable = <T extends Parameters<typeof v.union>[0]>(t: T) => v.union(t, v.null());

export const lane = v.union(v.literal("without"), v.literal("with"));

export const effect = v.object({
  peak_before_kw: v.number(),
  peak_after_kw: v.number(),
  saving_usd: v.number(),
});

export const decision = {
  decision_id: v.string(),
  ts: v.string(),
  device_id: v.string(),
  action: v.string(),
  value: nullable(v.number()),
  reason_code: v.string(),
  inside_rules: v.boolean(),
  status: v.union(v.literal("executed"), v.literal("undone")),
  effect,
};

// decisions:record rows: Decision + lane, explanation, explanation_source
export const decisionRecord = v.object({
  ...decision,
  lane,
  explanation: v.string(),
  explanation_source: v.union(v.literal("ai"), v.literal("template")),
});

export const command = {
  command_id: v.string(),
  lane,
  ts: v.string(),
  device_id: v.string(),
  action: v.union(
    v.literal("on"),
    v.literal("off"),
    v.literal("start"),
    v.literal("delay"),
    v.literal("reduce"),
    v.literal("restore"),
  ),
  value: nullable(v.number()),
  decision_id: nullable(v.string()),
  issued_by: v.union(v.literal("engine"), v.literal("owner")),
};

export const commandObject = v.object(command);

export const delivery = v.union(v.literal("queued"), v.literal("sent"), v.literal("acked"), v.literal("failed"));

export const reading = v.object({
  hub_id: v.string(),
  channel: v.number(),
  device_id: v.string(),
  ts: v.string(),
  raw_w: v.number(),
  scale: v.number(),
  power_kw: v.number(),
});

export const deviceMapRow = v.object({
  hub_id: v.string(),
  channel: v.number(),
  device_id: v.string(),
  scale: v.number(),
});

export const proposal = v.object({
  proposal_id: v.string(),
  ts: v.string(),
  kind: v.union(
    v.literal("importance"),
    v.literal("peak_cap"),
    v.literal("authority"),
    v.literal("undo_decision"),
    v.literal("customer_event"),
    v.literal("resolve_escalation"),
  ),
  payload: v.any(),
  summary: v.string(),
  status: v.union(v.literal("pending"), v.literal("confirmed"), v.literal("cancelled"), v.literal("expired")),
  created_by: v.string(),
  confirmed_via: nullable(v.union(v.literal("ui"), v.literal("asi_one"))),
  expires_at: nullable(v.string()),
});

export const bill = {
  period: v.string(),
  energy_kwh: v.number(),
  energy_cost_usd: v.number(),
  demand_charges: v.array(v.object({ name: v.string(), peak_kw: v.number(), cost_usd: v.number() })),
  total_usd: v.number(),
  tariff_id: v.string(),
};

export const billObject = v.object(bill);

export const backtestResult = {
  dataset: v.string(),
  month: v.string(),
  policies: v.record(v.string(), billObject),
  checks: v.object({
    baseline_matches_raw: v.boolean(),
    energy_conserved: v.boolean(),
    rule_violations: v.number(),
  }),
  assumptions_id: v.string(),
};

export const backtestResultObject = v.object(backtestResult);

export const deviceBlock = v.object({
  lane,
  device_id: v.string(),
  block_start: v.string(),
  avg_kw: v.number(),
  source: v.union(v.literal("simulated"), v.literal("measured")),
});

export const escalation = v.object({
  escalation_id: v.string(),
  lane,
  ts: v.string(),
  block_start: v.string(),
  problem: v.any(),
  options: v.array(v.any()),
  default_option_id: v.string(),
  deadline_sim_ts: v.string(),
  status: v.union(
    v.literal("open"),
    v.literal("resolved"),
    v.literal("awaiting_owner"),
    v.literal("expired_default"),
  ),
  resolved_by: nullable(v.union(v.literal("claude"), v.literal("owner"), v.literal("default"))),
  chosen_option_id: nullable(v.string()),
  rationale: nullable(v.string()),
});

export const contextSnapshot = v.object({
  ts: v.string(),
  weather: v.optional(v.any()),
  prices: v.optional(v.any()),
  events: v.optional(v.any()),
  crowd_effect: v.optional(v.any()),
});
