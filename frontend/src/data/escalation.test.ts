import { beforeEach, expect, it } from "vitest";
import type { Escalation, WsMessage } from "@/types";
import { escalationRow } from "./rows";
import { escalationMessage } from "./spacetime";
import { emptyTables, useLive } from "./useLive";
import { useSim } from "@/store/sim";

const e: Escalation = {
  escalation_id: "e_g73", lane: "with", ts: "2026-07-18T00:00:00Z", updated_ts: "2026-07-18T00:01:00Z",
  block_start: "2026-07-18T00:15:00Z", deadline_sim_ts: "2026-07-18T00:10:00Z",
  problem: { forecast_peak_kw: 44, target_kw: 40, excess_kw: 4, reason: "No in-rules move" },
  options: [{ option_id: "accept_overrun", summary: "Accept overrun", actions: [], projected: { peak_kw: 44, cost_delta_usd: 80, max_indoor_temp_change_c: null }, rule_breaks: [{kind: "cap_overrun", amount: 4, unit: "kW"}], within_authority: false, harm_score: 4/3, rank: 1 }],
  default_option_id: "accept_overrun", active_option_id: "accept_overrun", status: "open", resolved_by: null, chosen_option_id: null, rationale: null,
  claude_attempts: [{ ts: "2026-07-18T00:01:00Z", option_id: "accept_overrun", accepted: false, reason: "outside_authority", rationale: "Keep service running" }],
};
const notice = { explanation: "Claude chose an option outside authority. The safe fallback remains in force.", explanation_source: "template" as const };

beforeEach(() => useLive.getState().replaceTables(emptyTables()));

it("round-trips attempts and explanation through live rows and viewer messages", () => {
  const row = escalationRow(e, notice.explanation, notice.explanation_source);
  expect(JSON.parse(row.claude_attempts_json)).toEqual(e.claude_attempts);
  expect(row.explanation).toEqual(notice.explanation);
  expect(escalationMessage(row, e)).toEqual({type: "escalation", data: e, ...notice});
});

it("keeps verdict and explanation in both live stores on ws fallback", () => {
  const message: WsMessage = {type: "escalation", data: e, ...notice};
  useLive.getState().applyViewerMessages([message]);
  useSim.getState().applyMessages([message]);
  expect(useLive.getState().live_escalation[0].explanation).toEqual(notice.explanation);
  expect(useSim.getState().escalations[e.escalation_id].claude_attempts).toEqual(e.claude_attempts);
  expect(useSim.getState().escalations[e.escalation_id].explanation).toEqual(notice.explanation);
});

it("tick escalation updates retain the published explanation", () => {
  useSim.getState().applyMessages([{type: "escalation", data: e, ...notice}]);
  const tick = { lane: "with", ts: e.updated_ts, hub: { tick_id: 5, devices: [] }, meter: { total_kw: 44 }, new_decisions: [], new_escalations: [{...e, status: "obsolete"}] };
  useSim.getState().applyMessages([{type: "tick", data: tick} as unknown as WsMessage]);
  expect(useSim.getState().escalations[e.escalation_id].explanation).toEqual(notice.explanation);
  expect(useSim.getState().escalations[e.escalation_id].status).toBe("obsolete");
});
