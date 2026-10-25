// hubs:heartbeat (ESP32) · hubs:status (runtime). CONTRACTS.md §6. `last_seen` is real (wall-clock) time: the ESP32's
// liveness, not sim time. hubs:status is not in §6 yet (contract question for Kritazya).

import { v } from "convex/values";
import { mutation, query } from "./_generated/server";
import { hubViews } from "./liveness";

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

// Every hub with an "online" | "offline" view (last_seen older than 30 s, by Convex's clock). A query's result is cached
// while the rows it read stay the same, and time passing does not change them: callers pass `at` (any value that
// changes as often as they want a fresh answer, e.g. the current 5 s bucket) so a stale offline view is never served.
export const status = query({
  args: { at: v.optional(v.number()) },
  handler: async (ctx) => hubViews(ctx, Date.now()),
});
