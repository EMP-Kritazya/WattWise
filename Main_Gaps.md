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
| G05 | Warm-up / starting stats | **Decided by Kritazya (2026-10-24).** `warm_up(WarmUpHistory)`: 4 weeks of per-device 15-min blocks from NREL ComStock, scaled to the kitchen (`calibrated_model`); the engine meters the month's history days for month-to-date. Month to date is published in SpacetimeDB `live_tick`; `WarmUpHistory.month_to_date` stays null in this build (G65). Scenario fake starting stats are replaced (fixtures to regenerate) | ComStock county + scale recorded in DATA_AND_PROOF.md | ✔ |
| G34 | Catalog `params` | **Filled.** Keys per power model: fixed `{}` · cycling `{duty_idle_pct, duty_busy_pct}` · thermal `{setpoint_c}` · demand_driven `{idle_kw, kw_per_order}` · job `{cycle_min}`. The top-level `EquipmentType.min_power_pct` is removed; `default_limits` is the only source | Calibrated values per type (Ashirwad, FSTC / ENERGY STAR) | ☐ |

## B. API and messages
| ID | Topic | Demo decision | Final design | |
|---|---|---|---|---|
| G06 | Clock response | **Decided (2026-10-24).** `ClockState { playing, speed, sim_ts, tick_id, paused_reason }`; `slowed_reason` removed; `paused_reason` null \| manual \| hub_waiting \| sim_host_offline \| run_complete; plus `day_index`, `run_days`, `phase` (G57) | — | ✔ |
| G07 | "→ ok" | **Filled.** `{ "ok": true }` | — | ✔ |
| G08 | `GET /api/kitchen`, errors | **Filled.** `{ config, devices, tariff }`; errors `{ detail }` (422 RuleError, 404 unknown id) | — | ✔ |
| G09 | Id formats | **Filled.** `run_0001`, `chat_0001`; `months` = list of `"YYYY-MM"` | — | ✔ |
| G10 | Health values | **Filled.** `kitchen_impl` fake\|real · `live_transport` spacetime\|ws · `store` convex\|memory · `hardware` off\|sim_bridge\|esp32 · `sim_host` connected\|offline | — | ✔ |
| G11 | `warning.data` | **Filled.** cap_unreachable `{unavoidable_kw, peak_cap_kw, target_kw}` · sim_host_offline `{last_tick_id}` · hub_offline `{device_id, hub_id}` · live_transport_down `{}` · store_down `{}` | — | ✔ |

## C. Engine behaviour (decided 2026-10-24 unless marked ☐)
| ID | Topic | Demo decision | Final design | |
|---|---|---|---|---|
| G12 | Option actions | **Filled.** Option `actions` are templates (`decision_id: null`). The fallback's Commands are issued in the step the escalation opens (`escalation_fallback`); a later choice issues **new** Commands with `escalation_choice` Decisions in the next step | — | ✔ |
| G13 | `rule_breaks.kind` | **Filled.** `cap_overrun` · `below_min_power` · `past_deadline` · `over_max_reduce` · `over_max_delay`; any option whose projected peak is over the target lists `cap_overrun` | — | ✔ |
| G14 | `cost_delta_usd` baseline | **Decided by Kritazya.** `cost_delta_usd = optimized_cost_usd − baseline_cost_usd`, `saving_usd = −cost_delta_usd`. Options: baseline = in-rules plan holding the target exactly (so it is the option's extra cost). Decisions: baseline = the plan before this move | — | ✔ |
| G15 | Default option | **Decided (proposed by Claude, agreed direction by Kritazya; confirm the tolerances).** Engine ranks options by `harm_score` = Σ rule-break amount ÷ the owner's tolerance for that kind (authority bounds), within authority first, then cost. Fallback = rank 1 if within authority, else `ask_owner`; applied the moment the escalation opens; Claude gets the ranked list and may pick any option | Add comfort to harm once an HVAC model exists | ✔ |
| G16 | Option ids | **Filled.** By type: `deep_reduce_<type_id>`, `extend_delay_<type_id>`; actions list every affected device | — | ✔ |
| G17 | `awaiting_owner`, deadline | **Decided by Kritazya.** Open when a block starting within 30 sim min can't be held in-rules. Deadline = `max(ts + 5, min(ts + 15, block_start − 5))` sim min. `awaiting_owner` keeps Claude's pick + rationale; the fallback stays meanwhile. The owner may pick any option before the deadline (G61) | — | ✔ |
| G18 | Decision `escalated` status | **Filled.** Removed. Decision `status`: executed \| undone; the Escalation itself carries the hard case | — | ✔ |
| G19 | Owner command timing | **Filled.** `owner_command()` is recorded by the engine and returned in the next step's `new_commands` (no separate queue); delivered in the following `sim_tick` | — | ✔ |
| G20 | Delay semantics | **Filled.** `value` = minutes from when the hub applies it; on an idle job device it holds the next job (`waiting`); on a waiting job it replaces the hold; idle job devices report `off` | — | ✔ |
| G21 | Ack clamping | **Filled.** `ok: true` + same value = applied · `ok: true` + different `applied_value` = applied but clamped (`reason: out_of_range`) · `ok: false` = not applied (`job_running` \| `already_off` \| `unknown_device`) | — | ✔ |
| G22 | `snapshot()` | **Decided by Kritazya.** Pure, per lane: `{ tick_id, sim_ts, lane, control, peak_mode, config, meter, forecast_kw, forecast_ts, devices, active_commands, owed_kwh, open_escalations, warnings, recent_decisions (20), context, id_counters }`. The engine keeps only state needed for future decisions | — | ✔ |
| G23 | Indoor temperature | **Filled.** One dining-room temperature per kitchen, shared by every HVAC unit; `TickState.indoor_temp_c` copies it | — | ✔ |
| G24 | Forecast for `without` | **Filled.** Both lanes get `forecast_kw` on decision ticks (the chart draws only `with`) | — | ✔ |
| G35 | `minimize` mode, slowdown | **Decided by Kritazya.** Target = highest closed-block peak of the 4 previous same weekdays (history), a hard limit for the local day; no history → month peak so far. **No clock slowdown** (`ESCALATION_SPEED`, `slowed_reason` removed): fallback at once, Claude async, manual pause only | See Q4 | ✔ |

## D. AI tools
| ID | Topic | Demo decision | Final design | |
|---|---|---|---|---|
| G25 | Tool inputs, Proposal payloads | **Filled.** Inputs: `explain_decision {decision_id}` · `what_if {device_id, action, value, at, lane?}` (lane default `with`) · `get_bill {period}` · `propose_importance_change {device_id, importance, limits, summary}` · `propose_peak_cap_change {peak_mode, peak_cap_kw, summary}` · `propose_escalation_choice {escalation_id, option_id, summary}` · `propose_undo {decision_id, summary}` · `propose_customer_event {customers, duration_min, start_sim_ts, summary}`. Proposal `payload` per kind = the same fields without `summary`; `authority` payload = ClaudeAuthority. `created_by: "ai"` only | — | ✔ |

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
| G36 | Peak-period demand charge | **Decided by Kritazya.** Meter keeps `month_peak_kw` (general) and adds `on_peak_month_peak_kw` (windowed charge) + `energy_kwh_month`; each charge billed on its own peak in costs, projections, snapshots and backtests; `live_tick` gets both columns. Tests for on-peak, off-peak and billing-month boundaries | — | ✔ |
| G37 | Small readings | **Filled (fixtures).** `over_max_delay` counts from the first delay applied · `explain_decision` returns the Decision object · the toy simulation's 20 % clamp floor is fixture-only, not contract | — | ✔ |

## I. Engine decisions (2026-10-24; Kritazya's answers + fixes chosen to match the API and UI)
| ID | Topic | Decision | |
|---|---|---|---|
| G38 | Engine warnings | TickState gets `warnings: [Warning]`; Warning = `{code, message, data}` (same as the ws message without `type`) | ✔ |
| G39 | Escalation lifecycle | `obsolete` status; one active escalation per lane per block, updated in place (`updated_ts`); `active_option_id`; executed commands never auto-reversed | ✔ |
| G40 | Reduce base | `reduce` value and `min_power_pct` are % of `rated_kw` (power cap); SIMULATION.md and the hub follow it | ✔ |
| G41 | Forecast horizon | `forecast(120)` fixed; block 0 = block in progress | ✔ |
| G42 | Ids | One shared monotonically increasing counter per type across lanes; runtime steps `without` then `with`; `Kitchen.build_lanes` | ✔ |
| G43 | `what_if.at` | Sim ts where the hypothetical starts, within the 2 h horizon; read-only; lane chosen by the caller (default `with`) | ✔ |
| G44 | Job prediction | Idle jobs forecast from per-device history; `waiting` jobs are known; holds are `delay` with the hub auto-releasing; `delay 0` clears a hold | ✔ |
| G45 | Forecast granularity | Per device, per block; live ratio from always_on devices; crowd multiplier on demand_driven only | ✔ |
| G46 | Ledger | Live: owed = expected − actual (measured, an estimate; physics does catch-up). Replay: the replay plant repays exactly (conservation test runs there) | ✔ |
| G47 | Command lifecycle | Desired-state diff, no re-sends; restore by `floor(max_reduce_min/5)` decision ticks; cooldown = `max_reduce_min`; no new reduce in the last `max_reduce_min` before close | ✔ |
| G48 | Acks | Clamped → active at applied value; rejected → not active, not retried this block; `unknown_device` → never again; no ack → not applied | ✔ |
| G49 | Deadlines | Effective deadline = `min(must_finish_by, close)`; hold ≤ `max_delay_min` from the first applied delay | ✔ |
| G50 | Undo | Only executed reduce/delay still in force (G66): reduce → restore; delay → start (waiting) or delay 0 (idle hold); Command `issued_by: owner`, `decision_id` = the undone decision | ✔ |
| G51 | Savings attribution | Marginal in plan order; demand only above the month's already-paid per-charge peaks | ✔ |
| G52 | Billing boundaries | Local day and calendar month in `tariff.timezone`; `cost_usd_today` includes demand charges added today | ✔ |
| G53 | `without` lane | Meters and forecasts only; owner commands go to both lanes (fair comparison); `owner_command` records an `owner_override` Decision | ✔ |
| G54 | Measured readings | Engine recomputes `total_kw`; unused in this build (everything simulated) | ✔ |
| G55 | Replay | Same `Kitchen`; 15-min rows → HubReport-shaped objects; replay plant applies commands; fallback-only escalations | ✔ |

## J. Multi-day runs and fake history (2026-10-24, Kritazya)
| ID | Topic | Decision | |
|---|---|---|---|
| G56 | Run length | `KitchenConfig.run_days` (default 1; Builder 1 · 3 · 7 · 14). A year is backtest-only | ✔ |
| G57 | Day lifecycle | ClockState + `day_index`, `run_days`, `phase` (service \| overnight \| closed); `paused_reason: run_complete`; `sim/control` action `next_day` | ✔ |
| G58 | Closed hours | Ticked, not skipped: max speed, `sim_tick.fast_forward`, `is_open: false`; every tick metered, so always-on load is billed. Runtime publishes overnight once per 15-min block | ✔ |
| G59 | Fake history | `contracts/fixtures/history/`: ~2 months of per-device blocks (`fixture_synthetic`, `simulated`) + daily inputs; the engine uses the last 4 weeks, exactly as with ComStock | ✔ |
| G60 | Reconnect cue | The hub answers the replayed tick whose `tick_id` = `hub_welcome.tick_id` (Ashirwad's Q3) | ✔ |

## K. Doc sync (2026-10-24): behaviour pinned so every doc says the same thing
| ID | Topic | Decision | |
|---|---|---|---|
| G61 | Owner window | The owner resolves an escalation before its deadline, like Claude; after it the escalation is `expired_default` and the Proposal expires | ✔ |
| G62 | `cap_unreachable` cadence | Once per block, on the decision tick it first appears | ✔ |
| G63 | Closed hours | No reductions or holds start outside `operating_hours`; overnight the engine meters, forecasts and may escalate | ✔ |
| G64 | Asking Claude | Once per escalation, when it opens; updates are published (ws `escalation`, `live_escalation` upsert), not re-asked; a late or stale answer is returned unchanged / RuleError and the Concierge reports what is in force | ✔ |
| G65 | Month-to-date restore | `WarmUpHistory.month_to_date` is null in this build; restoring from `live_tick` is for a later resume-after-restart (otherwise a reset would double-count) | ✔ |
| G66 | Undo window | Only while the decision's command is in force (API 422 otherwise); `explain_decision` reads `recent_decisions`, else Convex `decisions` | ✔ |
| G67 | Escalation bookkeeping | `problem.forecast_peak_kw` = forecast after in-rules moves (what `accept_overrun` leaves); `expired_default` sets `resolved_by: "default"`; `default_option_id` never changes after opening | ✔ |

## Open questions for Kritazya
- **Q1 — clock slowdown during escalations.** Answered: dropped. Fallback at once, Claude async, manual pause only (G35).
- **Q2 — where month-to-date stats live.** Answered: SpacetimeDB `live_tick` (everything runs in simulation for now); seeded from
  the ComStock warm-up; not read back in this build (G05, G65).
- **Q3 — commit and share.** Commit `architecture-separation` so Suyog and Ashirwad can branch from it?
- **Q4 — `minimize` target below a peak already paid.** When this month's peak is already above the 4-week target, holding the
  lower target costs comfort and delays without lowering the `max_demand` charge (only the on-peak charge or future months
  benefit). Keep the hard 4-week target as decided, or use `max(4-week target, month_peak_kw)`?
- **Q5 — where `run_backtest` lives.** It reads data files (I/O), so it can't live in the no-I/O engine, yet the facade exports it
  as `from engine import run_backtest`. Recommended: implement it in `backend/backtest/runner.py` and have the API import
  `from backtest import run_backtest` (a one-line facade change in CLAUDE.md, CONTRACTS.md §3 and SUYOG.md). Alternative: keep
  the name and let `engine/__init__.py` re-export it lazily as the one documented exception to the boundary rule.
