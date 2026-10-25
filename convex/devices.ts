// devices:report (ESP32, and the runtime for the browser hub when HARDWARE=sim_bridge). CONTRACTS.md §6.
// devices:latest · devices:map · devices:mapChannel are not in §6 yet (contract question for Kritazya): the runtime needs
// to read Readings back and know the device map, and the map has to be set up once per demo kitchen.

import { v } from "convex/values";
import { mutation, query } from "./_generated/server";
import { args, mapChannel as mapChannelWrite, reportReading } from "./writes";

const strip = <T extends { _id: unknown; _creationTime: unknown }>({ _id, _creationTime, ...row }: T) => row;

export const report = mutation({ args: args["devices:report"], handler: reportReading });

// The newest Reading of every mapped channel of one hub (channels with no reading yet are left out).
export const latest = query({
  args: { hub_id: v.string() },
  handler: async (ctx, { hub_id }) => {
    const channels = await ctx.db
      .query("device_map")
      .withIndex("by_hub_channel", (q) => q.eq("hub_id", hub_id))
      .collect();
    const readings = [];
    for (const { channel } of channels) {
      const newest = await ctx.db
        .query("readings")
        .withIndex("by_hub_channel", (q) => q.eq("hub_id", hub_id).eq("channel", channel))
        .order("desc")
        .first();
      if (newest !== null) readings.push(strip(newest));
    }
    return readings;
  },
});

export const map = query({
  args: {},
  handler: async (ctx) => (await ctx.db.query("device_map").collect()).map(strip),
});

// Set up once per demo kitchen.
export const mapChannel = mutation({ args: args["devices:mapChannel"], handler: mapChannelWrite });
