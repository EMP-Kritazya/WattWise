# Main_Gaps.md — open design points, the demo decision in force, and what's left for the final design

Owner: **Kritazya**. Every gap the fixture builder found (G01–G35) has a **demo decision** that is now written into
`docs/CONTRACTS.md`, and the shared fixtures (`contracts/fixtures/`) follow it, so all three teammates build on the same
answer. The **final design** column is what Kritazya will redesign later. When a final decision lands: update
`docs/CONTRACTS.md` → run `contract-sync` → rerun `fixture-builder` → tick the row here.

Goal every decision serves: an automated system that keeps a restaurant's 15-minute peak demand low so owners stop paying
for peaks, without stopping service, with every number computed by tested code and honestly labeled.

Legend: **Decided by Kritazya** = your instruction · **Filled** = chosen here to fit the goal, open to change · ☐ = final design pending.

## A. Scenario, tariff and data
| ID | Topic | Demo decision (in force now) | Final design | |
|---|---|---|---|---|
| G01 | Demo Café equipment | **Decided by Kritazya.** All 11 catalog types: hvac × 2, every other type × 1, catalog default limits, except dishwasher `must_finish_by: "19:30"` (catalog default stays 15:30) and ice machine `22:00`. The deadline is fake data but a hard owner limit for the engine; only an escalation option can exceed it, within authority | Real kitchens from the Builder; defaults from FSTC / ENERGY STAR figures | ☐ |
| G02 | Tariff | **Decided by Kritazya.** One made-up, fixed tariff `demo_tariff_v1` (label `illustrative`), identical in every demo run: energy $0.22/kWh off-peak, $0.38/kWh peak 16:00–21:00 local; demand $20/kW monthly max + $8/kW peak-period (16:00–21:00) max. New `Tariff` shape; the engine bills with it | Real OpenEI URDB commercial rate for the restaurant's area (same region as the ComStock county) | ☐ |
| G03 | Events source | **Decided by Kritazya.** Fixtures use one recorded sports event (`source: "demo_events"`, `label: "recorded"`); `source` is a free string | Suyog picks a real events API reachable from Fetch.ai (e.g. Ticketmaster Discovery) | ☐ |
| G04 | Scenario start | **Decided by Kritazya.** Friday 17 July 2026, 17:30 local = `2026-07-18T00:30:00Z` | — | ✔ |
| G05 | Warm-up / starting stats | **Decided by Kritazya.** Fake starting stats in the scenario (month peak, energy and cost so far) so everyone can build | Real month-to-date stats come from stored history (**SpacetimeDB**, per Kritazya; see Q2 below) and the engine's warm-up source | ☐ |
| G34 | Catalog `params` | **Filled.** Keys per power model: fixed `{}` · cycling `{duty_idle_pct, duty_busy_pct}` · thermal `{setpoint_c}` · demand_driven `{idle_kw, kw_per_order}` · job `{cycle_min}`. The top-level `EquipmentType.min_power_pct` is removed; `default_limits` is the only source | Calibrated values per type (Ashirwad, FSTC / ENERGY STAR) | ☐ |

## B. API and messages
| ID | Topic | Demo decision | Final design | |
|---|---|---|---|---|
| G06 | Clock response | **Filled.** `ClockState { playing, speed, sim_ts, tick_id, paused_reason, slowed_reason }` returned by `POST /api/sim/control` and used by the ws `clock` message | — | ✔ |
| G07 | "→ ok" | **Filled.** `{ "ok": true }` | — | ✔ |
| G08 | `GET /api/kitchen`, errors | **Filled.** `{ config, devices, tariff }`; errors `{ detail }` (422 RuleError, 404 unknown id) | — | ✔ |
| G09 | Id formats | **Filled.** `run_0001`, `chat_0001`; `months` = list of `"YYYY-MM"` | — | ✔ |
| G10 | Health values | **Filled.** `kitchen_impl` fake\|real · `live_transport` spacetime\|ws · `store` convex\|memory · `hardware` off\|sim_bridge\|esp32 · `sim_host` connected\|offline | — | ✔ |
| G11 | `warning.data` | **Filled.** cap_unreachable `{unavoidable_kw, peak_cap_kw}` · sim_host_offline `{last_tick_id}` · hub_offline `{device_id, hub_id}` · live_transport_down `{}` · store_down `{}` | — | ✔ |

## C. Engine behaviour (all draft until the engine is designed)
| ID | Topic | Demo decision | Final design | |
|---|---|---|---|---|
| G12 | Option actions | **Filled.** Option `actions` are templates (`decision_id: null`). Applying an option issues **new** Commands with `escalation_choice` Decisions in the next step | — | ✔ |
| G13 | `rule_breaks.kind` | **Filled.** `cap_overrun` · `below_min_power` · `past_deadline` · `over_max_reduce` · `over_max_delay`; any option whose projected peak is over the target lists `cap_overrun` | — | ✔ |
| G14 | `cost_delta_usd` baseline | **Filled.** Extra cost versus holding the target with no rule broken (demand charge on the overrun + energy cost change) | Engine design | ☐ |
| G15 | Default option | **Filled.** `accept_overrun` if within authority (it changes no device), else `ask_owner` | Engine may rank by harm (cost, comfort, rule breaks) | ☐ |
| G16 | Option ids | **Filled.** By type: `deep_reduce_<type_id>`, `extend_delay_<type_id>`; actions list every affected device | — | ✔ |
| G17 | `awaiting_owner`, deadline | **Filled.** `chosen_option_id` = Claude's pick, `resolved_by: "claude"`, `rationale` kept; owner confirms or picks another. Deadline = `ts + 15 sim min`, never later than `block_start − 5 min` | Engine design (lead time, deadline rule) | ☐ |
| G18 | Decision `escalated` status | **Filled.** Removed. Decision `status`: executed \| undone; the Escalation itself carries the hard case | — | ✔ |
| G19 | Owner command timing | **Filled.** `owner_command()` is recorded by the engine and returned in the next step's `new_commands` (no separate queue); delivered in the following `sim_tick` | — | ✔ |
| G20 | Delay semantics | **Filled.** `value` = minutes from when the hub applies it; on an idle job device it holds the next job (`waiting`); on a waiting job it replaces the hold; idle job devices report `off` | — | ✔ |
| G21 | Ack clamping | **Filled.** `ok: true` + same value = applied · `ok: true` + different `applied_value` = applied but clamped (`reason: out_of_range`) · `ok: false` = not applied (`job_running` \| `already_off` \| `unknown_device`) | — | ✔ |
| G22 | `snapshot()` | **Filled.** Per lane (runtime uses the `with` lane): `{ config, devices, meter, context, recent_decisions, open_escalations }` | Engine design | ☐ |
| G23 | Indoor temperature | **Filled.** One dining-room temperature per kitchen, shared by every HVAC unit; `TickState.indoor_temp_c` copies it | — | ✔ |
| G24 | Forecast for `without` | **Filled.** Both lanes get `forecast_kw` on decision ticks (the chart draws only `with`) | — | ✔ |
| G35 | `minimize` mode, slowdown details | **Filled.** Target = max(month peak so far, unavoidable load); escalate only when the forecast would set a **new** month peak that in-rules moves can't avoid; `problem.target_kw` = that target. Clock slowdown: `ESCALATION_SPEED` env (default 1); the hub is not told, it just receives ticks more slowly | Engine design; whether to keep the slowdown at all (Q1) | ☐ |

## D. AI tools
| ID | Topic | Demo decision | Final design | |
|---|---|---|---|---|
| G25 | Tool inputs, Proposal payloads | **Filled.** Inputs: `explain_decision {decision_id}` · `what_if {device_id, action, value, at}` · `get_bill {period}` · `propose_importance_change {device_id, importance, limits, summary}` · `propose_peak_cap_change {peak_mode, peak_cap_kw, summary}` · `propose_escalation_choice {escalation_id, option_id, summary}` · `propose_undo {decision_id, summary}` · `propose_customer_event {customers, duration_min, start_sim_ts, summary}`. Proposal `payload` per kind = the same fields without `summary`; `authority` payload = ClaudeAuthority. `created_by: "ai"` only | — | ✔ |

## E. Hub protocol
| ID | Topic | Demo decision | Final design | |
|---|---|---|---|---|
| G26 | `sim_build` initial state | **Filled.** Roster only (`state: "off"`, 0 kW, no `physical`); the simulation sets real state on tick 1 | — | ✔ |
| G27 | Surges | **Filled.** A surge appears once, in the tick it starts; the simulation keeps it active for `duration_min` | — | ✔ |
| G28 | Reconnect | **Filled.** Server re-sends `sim_build`, then replays every past `sim_tick` with `"replay": true` at full speed; the hub answers only the last one; the engine is not re-stepped | — | ✔ |

## F. SpacetimeDB and Convex
| ID | Topic | Demo decision | Final design | |
|---|---|---|---|---|
| G29 | `publish_ticks` payload | **Filled.** `{ live_tick: [both lanes], tick_history: [both lanes], live_device: [every device, both lanes], live_comparison: {…} }` as a JSON string; other reducers take the row as a JSON string | Kritazya (SpacetimeDB) | ☐ |
| G30 | Key columns | **Filled.** `live_device.key = "<lane>:<device_id>"`; single-row tables `id = 0`; auto ids `id`; `surge_id = "s_" + 4-digit id`; `created_at` real time | Kritazya (SpacetimeDB) | ☐ |
| G31 | `live_context`, forecast column | **Filled.** `live_context`: weather_summary, weather_label, prices_summary, prices_label, events_summary, events_label, crowd_effect. `live_tick.forecast_kw_json` keeps the **latest** forecast between decision ticks, with `forecast_ts` | Kritazya (SpacetimeDB) | ☐ |
| G32 | Convex function args | **Filled.** `commands:enqueue {command, lane, hub_id}` · `commands:ack {command_id, ok, applied_value, reason}` · `decisions:record {decisions: [Decision + lane + explanation + explanation_source]}` · `proposals:upsert {proposal}` · `bills:save {bill, lane}` · `backtest:save {run_id, results}` | Suyog (Convex) | ☐ |

## G. Agents
| ID | Topic | Demo decision | Final design | |
|---|---|---|---|---|
| G33 | Agent fields | **Filled.** `PriceRequest.region = "caiso_np15"` · AgentLog `kind` request\|response\|post\|error · agent names concierge, weather, grid, events, claude, engine · `crowd_effect.set_by` claude\|owner\|default · `Context.ts` = sim time stamped by the API on receipt (agents' own fetch time is in AgentLog `ts_real`). Grid prices are a market **signal** (forecast, Claude's context); the owner's bill always uses the tariff (G02) | Suyog (real sources) | ☐ |

## H. Readings the fixture builder chose (follow-ups)
| ID | Topic | Demo decision | Final design | |
|---|---|---|---|---|
| G36 | Peak-period demand charge | **Filled (fixtures).** Each demand charge is billed on its own peak, but option effects use the single Meter `month_peak_kw` as the already-paid level (Meter has no per-window peak) | Engine: track a month peak per demand window (likely a new Meter field) | ☐ |
| G37 | Small readings | **Filled (fixtures).** `over_max_delay` counts from the first delay applied · `explain_decision` returns the Decision object · the toy simulation's 20 % clamp floor is fixture-only, not contract | — | ✔ |

## Open questions for Kritazya
- **Q1 — clock slowdown during escalations.** You chose early escalation (guard 1). Keep the slowdown to 1× while Claude decides
  (guard 2, now in the contract and fixtures), or drop it and rely on early escalation + the safe default?
- **Q2 — where month-to-date stats live.** You said real stats come from SpacetimeDB. Today SpacetimeDB holds only live state
  (bounded tables) and Convex holds durable records (bills, `device_blocks`). Either keep a month-to-date table in SpacetimeDB,
  or let the engine restore month-to-date from Convex at start. Which one?
- **Q3 — commit and share.** Commit `architecture-separation` so Suyog and Ashirwad can branch from it?
