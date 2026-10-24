// The runtime's writes, as plain handlers shared by the single mutations (commands:enqueue, decisions:record, …) and by
// batch:apply, which applies one real second of them in order, in one transaction.

import { ObjectType, v } from "convex/values";
import { MutationCtx } from "./_generated/server";
import {
  backtestResultObject,
  billObject,
  commandObject,
  contextSnapshot,
  decisionRecord,
  deviceBlock,
  deviceMapRow,
  escalation,
  lane,
  proposal,
  reading,
} from "./validators";

export const args = {
  "commands:enqueue": { command: commandObject, lane, hub_id: v.union(v.string(), v.null()) },
  "commands:ack": {
    command_id: v.string(),
    ok: v.boolean(),
    applied_value: v.union(v.number(), v.null()),
    reason: v.union(v.string(), v.null()),
  },
  "devices:report": { reading },
  "devices:mapChannel": { row: deviceMapRow },
  "decisions:record": { decisions: v.array(decisionRecord) },
  "proposals:upsert": { proposal },
  "bills:save": { bill: billObject, lane },
  "backtest:save": { run_id: v.string(), results: v.array(backtestResultObject) },
  "kitchens:record": { config: v.any(), created_at: v.string() },
  "escalations:record": { escalation },
  "deviceBlocks:record": { blocks: v.array(deviceBlock) },
  "contextSnapshots:record": { context: contextSnapshot },
};

type Args<K extends keyof typeof args> = ObjectType<(typeof args)[K]>;

export async function enqueueCommand(ctx: MutationCtx, { command, lane, hub_id }: Args<"commands:enqueue">) {
  await ctx.db.insert("commands", { ...command, lane, hub_id, delivery: "queued" });
  return null;
}

// Same meaning as CommandAck: ok → acked, else failed. Ids restart with every kitchen build, so the newest command with
// that id is the one acked. An unknown command_id is ignored (the device never errors).
export async function ackCommand(ctx: MutationCtx, { command_id, ok }: Args<"commands:ack">) {
  const row = await ctx.db
    .query("commands")
    .withIndex("by_command_id", (q) => q.eq("command_id", command_id))
    .order("desc")
    .first();
  if (row !== null) await ctx.db.patch(row._id, { delivery: ok ? "acked" : "failed" });
  return null;
}

export async function reportReading(ctx: MutationCtx, { reading }: Args<"devices:report">) {
  await ctx.db.insert("readings", reading);
  return null;
}

// One row per hub_id + channel (replaced if it exists).
export async function mapChannel(ctx: MutationCtx, { row }: Args<"devices:mapChannel">) {
  const existing = await ctx.db
    .query("device_map")
    .withIndex("by_hub_channel", (q) => q.eq("hub_id", row.hub_id).eq("channel", row.channel))
    .first();
  if (existing === null) await ctx.db.insert("device_map", row);
  else await ctx.db.replace(existing._id, row);
  return null;
}

// Upsert by decision_id (an undo re-records it). Ids restart per kitchen build: the newest row with that id is replaced.
export async function recordDecisions(ctx: MutationCtx, { decisions }: Args<"decisions:record">) {
  for (const decision of decisions) {
    const existing = await ctx.db
      .query("decisions")
      .withIndex("by_decision_id", (q) => q.eq("decision_id", decision.decision_id))
      .order("desc")
      .first();
    if (existing === null) await ctx.db.insert("decisions", decision);
    else await ctx.db.replace(existing._id, decision);
  }
  return null;
}

export async function upsertProposal(ctx: MutationCtx, { proposal }: Args<"proposals:upsert">) {
  const existing = await ctx.db
    .query("proposals")
    .withIndex("by_proposal_id", (q) => q.eq("proposal_id", proposal.proposal_id))
    .order("desc")
    .first();
  if (existing === null) await ctx.db.insert("proposals", proposal);
  else await ctx.db.replace(existing._id, proposal);
  return null;
}

export async function saveBill(ctx: MutationCtx, { bill, lane }: Args<"bills:save">) {
  await ctx.db.insert("bills", { ...bill, lane });
  return null;
}

export async function saveBacktest(ctx: MutationCtx, { run_id, results }: Args<"backtest:save">) {
  for (const result of results) await ctx.db.insert("backtest_results", { ...result, run_id });
  return null;
}

export async function recordKitchen(ctx: MutationCtx, row: Args<"kitchens:record">) {
  await ctx.db.insert("kitchens", row);
  return null;
}

export async function recordEscalation(ctx: MutationCtx, { escalation }: Args<"escalations:record">) {
  const existing = await ctx.db
    .query("escalations")
    .withIndex("by_escalation_id", (q) => q.eq("escalation_id", escalation.escalation_id))
    .order("desc")
    .first();
  if (existing === null) await ctx.db.insert("escalations", escalation);
  else await ctx.db.replace(existing._id, escalation);
  return null;
}

export async function recordDeviceBlocks(ctx: MutationCtx, { blocks }: Args<"deviceBlocks:record">) {
  for (const block of blocks) await ctx.db.insert("device_blocks", block);
  return null;
}

export async function recordContextSnapshot(ctx: MutationCtx, { context }: Args<"contextSnapshots:record">) {
  await ctx.db.insert("context_snapshots", context);
  return null;
}

export const handlers: { [K in keyof typeof args]: (ctx: MutationCtx, a: Args<K>) => Promise<null> } = {
  "commands:enqueue": enqueueCommand,
  "commands:ack": ackCommand,
  "devices:report": reportReading,
  "devices:mapChannel": mapChannel,
  "decisions:record": recordDecisions,
  "proposals:upsert": upsertProposal,
  "bills:save": saveBill,
  "backtest:save": saveBacktest,
  "kitchens:record": recordKitchen,
  "escalations:record": recordEscalation,
  "deviceBlocks:record": recordDeviceBlocks,
  "contextSnapshots:record": recordContextSnapshot,
};
