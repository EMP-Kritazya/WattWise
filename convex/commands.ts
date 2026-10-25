// commands:forDevice (ESP32 subscribes) · commands:ack (ESP32) · commands:enqueue (runtime) · commands:failed (runtime).
// CONTRACTS.md §6. commands:failed is not in §6 yet (contract question for Kritazya).

import { v } from "convex/values";
import { Doc } from "./_generated/dataModel";
import { mutation, query } from "./_generated/server";
import { ackCommand, args, enqueueCommand } from "./writes";

const asCommand = ({ command_id, lane, ts, device_id, action, value, decision_id, issued_by }: Doc<"commands">) => ({
  command_id,
  lane,
  ts,
  device_id,
  action,
  value,
  decision_id,
  issued_by,
});

// Commands for one hub still waiting to be executed, oldest first, as Command shapes (CONTRACTS.md §1).
export const forDevice = query({
  args: { hub_id: v.string() },
  handler: async (ctx, { hub_id }) => {
    const waiting = [];
    for (const state of ["queued", "sent"] as const) {
      waiting.push(
        ...(await ctx.db
          .query("commands")
          .withIndex("by_hub_delivery", (q) => q.eq("hub_id", hub_id).eq("delivery", state))
          .collect()),
      );
    }
    waiting.sort((a, b) => a._creationTime - b._creationTime);
    return waiting.map(asCommand);
  },
});

// One hub's failed commands (nacked, or timed out by liveness:sweep) enqueued at or after `since_ms` (real ms; the
// runtime passes its kitchen build time, since command ids restart with every build), oldest first. A command retried
// once shows up once per failed row.
export const failed = query({
  args: { hub_id: v.string(), since_ms: v.number() },
  handler: async (ctx, { hub_id, since_ms }) =>
    (
      await ctx.db
        .query("commands")
        .withIndex("by_hub_delivery", (q) =>
          q.eq("hub_id", hub_id).eq("delivery", "failed").gte("_creationTime", since_ms),
        )
        .collect()
    ).map(asCommand),
});

export const ack = mutation({ args: args["commands:ack"], handler: ackCommand });

export const enqueue = mutation({ args: args["commands:enqueue"], handler: enqueueCommand });
