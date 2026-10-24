// Convex tables: CONTRACTS.md §6. Durable records + the ESP32 bridge; nothing here is read every tick by the UI.

import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";
import {
  backtestResult,
  bill,
  command,
  contextSnapshot,
  decisionRecord,
  delivery,
  deviceBlock,
  deviceMapRow,
  escalation,
  lane,
  proposal,
  reading,
} from "./validators";

export default defineSchema({
  kitchens: defineTable({ config: v.any(), created_at: v.string() }),
  decisions: defineTable(decisionRecord).index("by_decision_id", ["decision_id"]),
  commands: defineTable({ ...command, hub_id: v.union(v.string(), v.null()), delivery })
    .index("by_command_id", ["command_id"])
    .index("by_hub_delivery", ["hub_id", "delivery"]),
  readings: defineTable(reading).index("by_hub_channel", ["hub_id", "channel"]),
  device_map: defineTable(deviceMapRow).index("by_hub_channel", ["hub_id", "channel"]),
  hubs: defineTable({ hub_id: v.string(), last_seen: v.string(), firmware: v.union(v.string(), v.null()) }).index(
    "by_hub_id",
    ["hub_id"],
  ),
  proposals: defineTable(proposal).index("by_proposal_id", ["proposal_id"]),
  bills: defineTable({ ...bill, lane }),
  backtest_results: defineTable({ ...backtestResult, run_id: v.string() }).index("by_run_id", ["run_id"]),
  device_blocks: defineTable(deviceBlock).index("by_lane_device", ["lane", "device_id", "block_start"]),
  escalations: defineTable(escalation).index("by_escalation_id", ["escalation_id"]),
  context_snapshots: defineTable(contextSnapshot),
});
