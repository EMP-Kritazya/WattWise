import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import type { Escalation } from "@/types";
import { EscalationDetails } from "./EscalationCard";

const base: Escalation = {
  escalation_id: "e_0001", lane: "with", ts: "2026-07-18T00:00:00Z", updated_ts: "2026-07-18T00:01:00Z",
  block_start: "2026-07-18T00:15:00Z", deadline_sim_ts: "2026-07-18T00:10:00Z",
  problem: { forecast_peak_kw: 44, target_kw: 40, excess_kw: 4, reason: "No in-rules move" },
  options: [{ option_id: "accept_overrun", summary: "Accept overrun", actions: [], projected: { peak_kw: 44, cost_delta_usd: 80, max_indoor_temp_change_c: null }, rule_breaks: [{kind: "cap_overrun", amount: 4, unit: "kW"}], within_authority: false, harm_score: 4/3, rank: 1 }],
  default_option_id: "accept_overrun", active_option_id: "accept_overrun", status: "open", resolved_by: null, chosen_option_id: null, rationale: null,
  claude_attempts: [{ ts: "2026-07-18T00:01:00Z", option_id: "accept_overrun", accepted: false, reason: "outside_authority", rationale: "Keep service running" }],
};

it.each([
  ["open", "Safe fallback active"], ["resolved", "Claude choice accepted"],
  ["expired_default", "Deadline passed"], ["obsolete", "Risk passed"],
] as const)("renders %s with engine verdict and no owner choice controls", (status, label) => {
  const html = renderToStaticMarkup(<EscalationDetails escalation={{...base, status, explanation: "Published engine notice", explanation_source: "template"}} />);
  expect(html).toContain(label);
  expect(html).toContain("Published engine notice");
  expect(html).toContain("rejected: outside authority");
  expect(html).toContain("Outside authority");
  expect(html).not.toContain("<button");
  expect(html).not.toContain("Waiting for you");
});
