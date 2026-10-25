// Liveness rules, run in Convex (crons.ts every 10 s): real (wall-clock) time, never sim time. No energy math here.
// Mirrored by backend/store/memory.py (same constants, same rules) so STORE=memory behaves the same.
//
// - A command still `queued` or `sent` 15 s after it was enqueued (`_creationTime`) → delivery "failed". A late ack
//   still wins (commands:ack patches the newest row with that id).
// - A hub whose `last_seen` is older than 30 s is "offline" in the hubs:status view (a view, not a stored field).

import { internalMutation, QueryCtx } from "./_generated/server";

export const COMMAND_TIMEOUT_MS = 15_000;
export const HUB_OFFLINE_MS = 30_000;

export type HubView = { hub_id: string; last_seen: string; firmware: string | null; status: "online" | "offline" };

export async function hubViews(ctx: QueryCtx, now_ms: number): Promise<HubView[]> {
  const hubs = await ctx.db.query("hubs").collect();
  return hubs.map(({ hub_id, last_seen, firmware }) => ({
    hub_id,
    last_seen,
    firmware,
    status: now_ms - Date.parse(last_seen) > HUB_OFFLINE_MS ? "offline" : "online",
  }));
}

// Commands only wait on a hub_id (simulated-only commands have none and are never failed), so walk the known hubs
// through `by_hub_delivery` instead of scanning every queued command.
export const sweep = internalMutation({
  args: {},
  handler: async (ctx) => {
    const now_ms = Date.now();
    const hub_ids = new Set<string>();
    for (const hub of await ctx.db.query("hubs").collect()) hub_ids.add(hub.hub_id);
    for (const row of await ctx.db.query("device_map").collect()) hub_ids.add(row.hub_id);
    let failed = 0;
    for (const hub_id of hub_ids) {
      for (const state of ["queued", "sent"] as const) {
        const stale = await ctx.db
          .query("commands")
          .withIndex("by_hub_delivery", (q) =>
            q.eq("hub_id", hub_id).eq("delivery", state).lt("_creationTime", now_ms - COMMAND_TIMEOUT_MS),
          )
          .collect();
        for (const row of stale) await ctx.db.patch(row._id, { delivery: "failed" });
        failed += stale.length;
      }
    }
    const offline = (await hubViews(ctx, now_ms)).filter((h) => h.status === "offline").map((h) => h.hub_id);
    if (failed > 0 || offline.length > 0) console.log(`liveness: ${failed} command(s) failed; offline hubs: ${offline}`);
    return null;
  },
});
