// hubs:heartbeat (ESP32). CONTRACTS.md §6. `last_seen` is real (wall-clock) time: the ESP32's liveness, not sim time.

import { v } from "convex/values";
import { mutation } from "./_generated/server";

export const heartbeat = mutation({
  args: { hub_id: v.string() },
  handler: async (ctx, { hub_id }) => {
    const last_seen = new Date().toISOString();
    const hub = await ctx.db
      .query("hubs")
      .withIndex("by_hub_id", (q) => q.eq("hub_id", hub_id))
      .first();
    if (hub === null) await ctx.db.insert("hubs", { hub_id, last_seen, firmware: null });
    else await ctx.db.patch(hub._id, { last_seen });
    return null;
  },
});
