// commands:forDevice (ESP32 subscribes) · commands:ack (ESP32) · commands:enqueue (runtime). CONTRACTS.md §6.

import { v } from "convex/values";
import { mutation, query } from "./_generated/server";
import { ackCommand, args, enqueueCommand } from "./writes";

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
    return waiting.map(({ command_id, lane, ts, device_id, action, value, decision_id, issued_by }) => ({
      command_id,
      lane,
      ts,
      device_id,
      action,
      value,
      decision_id,
      issued_by,
    }));
  },
});

export const ack = mutation({ args: args["commands:ack"], handler: ackCommand });

export const enqueue = mutation({ args: args["commands:enqueue"], handler: enqueueCommand });
