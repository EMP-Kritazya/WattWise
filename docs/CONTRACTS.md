# Contracts

The single source of truth for every shape shared between the Frontend (UI + simulation + hub), the API/runtime/AI and the Engine.
- JSON is snake_case. Units in field names. Timestamps ISO 8601 with timezone.
- Backend: Pydantic models in `backend/contracts/`. Frontend: types generated from OpenAPI + `contracts/ws_messages.schema.json`
  + SpacetimeDB generated bindings + Convex generated types. Nothing hand written.
- SpacetimeDB rows and Convex documents carry the same snake_case fields as the shapes below.
- Change this file in the same commit as any shape change, and tell the team (use the `contract-sync` subagent),
  then regenerate `contracts/fixtures/` with the `fixture-builder` subagent.
- Sections marked **PROVISIONAL (engine TBD)** are the minimum the API and frontend build against while Kritazya finalises
  engine internals; their shapes are fixed, the engine behaviour behind them is not.

Contents: 1 Shared shapes · 2 S1 REST + WebSocket · 3 S2 Engine facade · 4 AI tools · 5 S3 SpacetimeDB ·
6 S4 Convex · 7 S5 Agent messages · 8 S6 Hub protocol (browser hub ↔ FastAPI) · 9 S7 Appliance interface (inside the browser)

---

## 1. Shared shapes

### Importance
`"always_on" | "flexible" | "deferrable"`

### EquipmentType (catalog entry, read-only, from `backend/data/equipment_catalog.json`)
```json
{ "type_id": "dishwasher", "name": "Dishwasher", "category": "water_heating",
  "default_importance": "deferrable", "rated_kw": 6.0,
  "power_model": "job", "params": { "cycle_min": 30 },
  "default_limits": { "max_delay_min": 60, "must_finish_by": "15:30" }, "source_note": "FSTC / ENERGY STAR" }
```
`default_limits`: the limits a new unit of this type starts with. They must pass `rules.py`
(a refrigeration device set to flexible needs `min_power_pct` ≥ 50).
`category`: cooling | refrigeration | cooking | water_heating | lighting | other.
`power_model`: fixed | cycling | thermal | demand_driven | job (see design/SIMULATION.md).
`params` keys per power model: fixed `{}` · cycling `{ duty_idle_pct, duty_busy_pct }` · thermal `{ setpoint_c }` ·
demand_driven `{ idle_kw, kw_per_order }` · job `{ cycle_min }`. Minimum power lives only in `default_limits.min_power_pct`.

### ImportanceLimits (depends on importance)
```json
{ "always_on":  {},
  "flexible":   { "min_power_pct": 40, "max_reduce_min": 30 },
  "deferrable": { "max_delay_min": 60, "must_finish_by": "15:30" } }
```
Examples only. Real starting values come from each EquipmentType's `default_limits`.
Food safety floor: refrigeration devices set to flexible must keep `min_power_pct` ≥ 50.

### KitchenConfig (built in the UI, sent to the API, passed to the engine)
```json
{ "name": "Demo Café",
  "equipment": [
    { "type_id": "hvac", "count": 2, "importance": "flexible", "limits": { "min_power_pct": 40, "max_reduce_min": 30 } },
    { "type_id": "walk_in_cooler", "count": 1, "importance": "flexible", "limits": { "min_power_pct": 50, "max_reduce_min": 30 } },
    { "type_id": "reach_in_fridge", "count": 1, "importance": "always_on", "limits": {} },
    { "type_id": "freezer", "count": 1, "importance": "always_on", "limits": {} },
    { "type_id": "ice_machine", "count": 1, "importance": "deferrable", "limits": { "max_delay_min": 60, "must_finish_by": "22:00" } },
    { "type_id": "fryer", "count": 1, "importance": "always_on", "limits": {} },
    { "type_id": "oven", "count": 1, "importance": "always_on", "limits": {} },
    { "type_id": "grill", "count": 1, "importance": "always_on", "limits": {} },
    { "type_id": "dishwasher", "count": 1, "importance": "deferrable", "limits": { "max_delay_min": 60, "must_finish_by": "19:30" } },
    { "type_id": "water_heater", "count": 1, "importance": "flexible", "limits": { "min_power_pct": 40, "max_reduce_min": 30 } },
    { "type_id": "lights", "count": 1, "importance": "always_on", "limits": {} }
  ],
  "peak_mode": "cap", "peak_cap_kw": 40.0,
  "operating_hours": { "open": "10:00", "close": "22:00" },
  "location": { "lat": 37.80, "lon": -122.44, "label": "Marina, San Francisco" },
  "owner_preferences": "Keep the dining room comfortable during dinner service.",
  "authority": "<ClaudeAuthority>",
  "tariff_id": "demo_tariff_v1",
  "seed": 42 }
```
This is the **Demo Café** config: all 11 catalog types (hvac × 2, every other type × 1) with catalog default limits, except
the dishwasher's `must_finish_by` moved to 19:30 so it matters during the 17:30–19:30 demo (fake data, but a hard owner limit for
the engine). Count 0 = not in this kitchen. Each unit becomes a Device with id `<type_id>_<n>` (e.g. `hvac_1`, `hvac_2`); the same
roster is sent to the simulation (`sim_build.devices`) and built into both engine lanes.
`peak_mode`: `minimize` (no fixed number: keep the month's 15-min peak as low as the rules allow; `peak_cap_kw` is null) |
`cap` (hold the owner's `peak_cap_kw`; going above it happens only through an escalation within `ClaudeAuthority.max_cap_overrun_kw`
or with owner confirmation — set that authority to 0 for a strictly hard limit).

### Tariff (passed to the engine as `Kitchen(config, tariff, ...)`; served by `GET /api/kitchen`)
```json
{ "tariff_id": "demo_tariff_v1", "name": "WattWise demo commercial rate", "label": "illustrative", "currency": "USD",
  "timezone": "America/Los_Angeles",
  "energy": [ { "name": "off_peak", "start": "00:00", "end": "16:00", "usd_per_kwh": 0.22 },
              { "name": "peak",     "start": "16:00", "end": "21:00", "usd_per_kwh": 0.38 },
              { "name": "off_peak", "start": "21:00", "end": "24:00", "usd_per_kwh": 0.22 } ],
  "demand": [ { "name": "max_demand",  "window": null,                              "usd_per_kw": 20.0 },
              { "name": "peak_demand", "window": { "start": "16:00", "end": "21:00" }, "usd_per_kw": 8.0 } ] }
```
Demo: one made-up tariff, identical in every run (`label: "illustrative"`). Later: a real OpenEI URDB rate for the restaurant's
area (`label: "urdb"`), same shape. Demand charges bill the highest 15-min average kW in the month (inside `window` when set).
The owner's bill always uses the tariff; Context grid prices are a market signal only.

### ClaudeAuthority (owner-set bounds for resolving escalations without asking)
```json
{ "enabled": true, "max_cap_overrun_kw": 3.0, "max_extra_delay_min": 20, "max_extra_reduce_min": 15,
  "may_go_below_min_power": false }
```
Engine marks each escalation option `within_authority` against these. The refrigeration food-safety floor (50 %) is never
crossable, whatever the authority says. `enabled: false` → every escalation goes to the owner.

### Device (live state of one unit)
```json
{ "device_id": "hvac_1", "type_id": "hvac", "name": "HVAC 1", "importance": "flexible",
  "state": "reduced", "power_kw": 4.8, "rated_kw": 12.0, "power_pct": 40, "source": "simulated",
  "physical": { "indoor_temp_c": 22.4 } }
```
`state`: off | on | reduced | waiting (deferred job queued) | running_job.
`source`: simulated | measured. Only a device fed by a real ESP32 reading (`ingest_reading`) is measured.
`power_pct` = round(100 × power_kw / rated_kw), set by the hub.
`physical` (optional, from the simulation, by power model): `indoor_temp_c` (thermal) · `box_temp_c` (cycling) ·
`dirty_racks`, `ice_level_pct`, `job_remaining_min` (job) · `orders_in_progress` (demand_driven). Unknown keys are ignored.

### HubReport (the hub's current state of one lane, sent every tick; the engine's only view of the kitchen)
```json
{ "hub_id": "sim_hub", "lane": "with", "tick_id": 1095, "ts": "2026-07-17T19:15:00Z", "total_kw": 38.2,
  "customers_per_hour": 64,
  "devices": [ "<Device>" ],
  "acks": [ "<CommandAck>" ],
  "source": "simulated" }
```
`acks`: one CommandAck for every Command of this lane delivered in this tick (empty otherwise), so the engine receives them.
`ts` = end of the simulated minute just stepped. `total_kw` = sum of `devices[].power_kw` (hub-computed, exact).
Top level `source`: simulated | mixed (at least one device is measured; set by the runtime after merging ESP32 readings).

### Reading (real ESP32 → Convex → runtime → engine)
```json
{ "hub_id": "esp32_1", "channel": 0, "device_id": "dishwasher_1", "ts": "...",
  "raw_w": 6.2, "scale": 1000, "power_kw": 6.2 }
```
`power_kw = raw_w × scale / 1000`. Bench loads draw watts, so each channel declares a `scale` in Convex
`device_map`; the UI labels such a device "measured (scaled)". Readings feed the `with` lane only.

### Command (engine → runtime → `sim_tick` → hub → appliance)
```json
{ "command_id": "c_0192", "lane": "with", "ts": "...", "device_id": "dishwasher_1",
  "action": "delay", "value": 20, "decision_id": "d_0041", "issued_by": "engine" }
```
`action`: on | off | start | delay (value = minutes) | reduce (value = power %) | restore.
`delay`: `value` minutes from when the hub applies it; on an idle job device it holds the next job (`waiting`); on a waiting job
it replaces the hold. Idle job devices report `state: "off"`.
`issued_by`: engine | owner (manual click, or an owner confirmed action from the UI or ASI:One).
`decision_id` is null for owner commands.

### CommandAck (hub → runtime → engine, inside each lane's HubReport)
```json
{ "command_id": "c_0192", "lane": "with", "ok": true, "applied_value": 20, "reason": null }
```
`ok: true` + `applied_value == value` → applied. `ok: true` + different `applied_value` → applied but clamped to a physical
limit (`reason: out_of_range`). `ok: false` → not applied (`reason`: job_running | already_off | unknown_device).
`reason` is null when applied unchanged. The next HubReport shows the real state.

### Decision (engine output)
```json
{ "decision_id": "d_0041", "ts": "...", "device_id": "dishwasher_1", "action": "delay", "value": 20,
  "reason_code": "avoid_new_peak", "inside_rules": true,
  "status": "executed",
  "effect": { "peak_before_kw": 46.0, "peak_after_kw": 40.0, "saving_usd": 120.0 } }
```
`status`: executed | undone. (The hard case is carried by the Escalation, not by a Decision status.)
There is no per-decision owner approval any more: anything outside the rules becomes an Escalation.
`reason_code`: avoid_new_peak | stay_under_cap | release_into_valley | catch_up | owner_override | escalation_choice.
`effect` is computed by the engine. Nobody else changes it.

### Context (Fetch agents → API → engine; numbers forwarded unchanged)
```json
{ "ts": "...",
  "weather": { "label": "live_api", "source": "open-meteo", "hourly": [ { "ts": "...", "temp_c": 24.1 } ] },
  "prices":  { "label": "live_api", "source": "caiso", "hourly": [ { "ts": "...", "usd_per_kwh": 0.31 } ], "stress": "high" },
  "events":  { "label": "live_api", "source": "ticketmaster",
               "items": [ { "name": "Giants vs Dodgers", "venue": "Oracle Park", "start": "...", "distance_km": 1.8, "expected_attendance": 40000 } ] },
  "crowd_effect": { "value": "medium", "set_by": "claude", "reason": "Game ends 22:00, 1.8 km away" } }
```
Partial posts merge. `label`: live_api | recorded (demo mode). `stress`: low | normal | high.
`ts` is stamped by the API in sim time when the post arrives. `crowd_effect.set_by`: claude | owner | default.
`events.source` is a free string naming the provider (demo fixtures: `demo_events`, one recorded sports event; the real provider
is Suyog's choice, e.g. Ticketmaster). Grid `prices` are a market signal for forecasts and Claude's context, not the bill (see Tariff).
`crowd_effect.value`: none | small | medium | large → crowd multiplier 1.00 / 1.10 / 1.25 / 1.40 (fixed table in the engine).
Runtime passes the current outdoor temperature and multiplier to the simulation in `sim_tick.inputs` (physical inputs).
Engine uses: weather → HVAC forecast; prices → energy cost and tie-breaks; crowd effect → forecast. Fetched periodically
(every `CONTEXT_INTERVAL_S`, default 600 real s, and on kitchen build); the engine always uses the latest it has.

### Escalation (engine → runtime → Claude or owner)
```json
{ "escalation_id": "e_0012", "lane": "with", "ts": "<sim ts>", "block_start": "<sim ts>",
  "problem": { "forecast_peak_kw": 44.0, "target_kw": 40.0, "excess_kw": 4.0, "reason": "dinner rush + hot evening" },
  "options": [
    { "option_id": "accept_overrun", "summary": "Let the peak reach 43 kW for one block",
      "actions": [], "projected": { "peak_kw": 43.0, "cost_delta_usd": 60.0, "max_indoor_temp_change_c": 0.0 },
      "rule_breaks": [ { "kind": "cap_overrun", "amount": 3.0, "unit": "kW" } ], "within_authority": true },
    { "option_id": "deep_reduce_hvac", "summary": "HVAC to 30 % for 15 min",
      "actions": [ "<Command>" ], "projected": { "peak_kw": 40.0, "cost_delta_usd": 0.0, "max_indoor_temp_change_c": 1.5 },
      "rule_breaks": [ { "kind": "below_min_power", "device_id": "hvac_1", "amount": 10, "unit": "pct" } ], "within_authority": false },
    { "option_id": "extend_delay_dishwasher", "summary": "Delay the dishwasher 20 min past its deadline", "actions": [ "<Command>" ],
      "projected": { "peak_kw": 40.0, "cost_delta_usd": 0.0, "max_indoor_temp_change_c": 0.0 },
      "rule_breaks": [ { "kind": "past_deadline", "device_id": "dishwasher_1", "amount": 20, "unit": "min" } ], "within_authority": true },
    { "option_id": "ask_owner", "summary": "Ask the owner", "actions": [], "projected": null, "rule_breaks": [], "within_authority": true } ],
  "default_option_id": "accept_overrun",
  "deadline_sim_ts": "<sim ts>", "status": "open",
  "resolved_by": null, "chosen_option_id": null, "rationale": null }
```
`status`: open | resolved | awaiting_owner | expired_default. `resolved_by`: claude | owner | default.
`awaiting_owner`: `chosen_option_id` and `rationale` hold Claude's outside-authority pick, `resolved_by: "claude"`; the owner
confirms it or picks another option (`resolved_by` becomes `owner`).
`deadline_sim_ts` = `ts + 15 sim min`, never later than `block_start − 5 min`.
Option ids are by type: `deep_reduce_<type_id>`, `extend_delay_<type_id>`; `actions` list every affected device.
Option `actions` are templates (`decision_id: null`); applying an option issues **new** Commands with Decisions
(`reason_code: escalation_choice`) in the next step.
`rule_breaks[].kind`: cap_overrun | below_min_power | past_deadline | over_max_reduce | over_max_delay. Every option whose
projected peak is above the target lists a `cap_overrun`.
`projected.cost_delta_usd`: extra cost versus holding the target with no rule broken (demand charge on the overrun + energy change).
In `minimize` mode the target is max(month peak so far, unavoidable load) and an escalation opens only when the forecast would
set a new month peak that in-rules moves can't avoid; `problem.target_kw` is that target.
Options: **2–3 evaluated alternatives** (`accept_overrun`, `deep_reduce_<device>`, `extend_delay_<device>`) **plus `ask_owner`**,
so 3–4 entries. Options and every number in them come from the engine. Food-safety breaks are never generated as options.
The default is `accept_overrun` if it is within authority (it changes no device), else `ask_owner`. Unresolved at the deadline →
nothing extra is done (equivalent to the overrun), status `expired_default`.

### Meter
```json
{ "ts": "...", "total_kw": 38.2, "block_avg_kw": 37.9, "block_start": "...",
  "month_peak_kw": 46.0, "peak_mode": "cap", "peak_cap_kw": 40.0, "target_kw": 40.0,
  "energy_kwh_today": 312.4, "price_usd_per_kwh_now": 0.31, "cost_usd_today": 61.20, "cost_usd_month": 1830.55 }
```
Every field is engine-computed from HubReports and the tariff (`price_usd_per_kwh_now`: current energy price the bill uses).
`target_kw`: what the engine is holding now (= `peak_cap_kw` in `cap` mode; engine-chosen in `minimize` mode). `peak_cap_kw` null in `minimize` mode.

### TickState (engine → runtime every step; runtime publishes it to SpacetimeDB) — PROVISIONAL (engine TBD)
```json
{ "lane": "with", "ts": "...", "hub": "<HubReport>", "meter": "<Meter>",
  "customers_per_hour": 64, "new_decisions": ["<Decision>"], "new_commands": ["<Command>"],
  "new_escalations": ["<Escalation>"], "indoor_temp_c": 22.4,
  "forecast_kw": [38, 41, 44, 39, 36, 35, 37, 40] }
```
`forecast_kw`: next 2 h in 15-min steps (8 values); present only on re-plan ticks, otherwise null.
`hub`: the HubReport this step was computed from (echoed). `customers_per_hour` copied from it; `indoor_temp_c` = the kitchen's one
dining-room temperature (shared by every HVAC unit's `physical.indoor_temp_c`). Both lanes carry `forecast_kw` on decision ticks.
`new_commands`: Commands issued this step (engine and owner); the runtime sends them in the **next** `sim_tick` and forwards the
`with` lane's commands for ESP32-mapped devices to Convex.

### LaneComparison (engine `compare_lanes(without, with_)`, attached by the runtime to every tick pair)
```json
{ "ts": "...", "saved_today_usd": 18.40, "peak_avoided_kw": 6.0,
  "month_peak_without_kw": 46.0, "month_peak_with_kw": 40.0 }
```
The browser shows these numbers; it never subtracts lanes itself.

### Proposal (AI suggestion waiting for owner confirmation)
```json
{ "proposal_id": "p_0007", "ts": "...", "kind": "importance",
  "payload": { "device_id": "walk_in_cooler_1", "importance": "always_on", "limits": {} },
  "summary": "Never touch the walk-in after 21:00", "status": "pending",
  "created_by": "ai", "confirmed_via": null, "expires_at": "<sim ts>" }
```
`kind`: importance | peak_cap | authority | undo_decision | customer_event | resolve_escalation.
`payload` per kind = the matching `propose_*` input without `summary`; `authority` payload = ClaudeAuthority. `created_by`: ai.
`status`: pending | confirmed | cancelled | expired. `confirmed_via`: ui | asi_one | null.
Applied by code (never by the model) when the owner confirms; the result is the normal facade call.

### Bill
```json
{ "period": "2026-07", "energy_kwh": 21840.0, "energy_cost_usd": 4210.55,
  "demand_charges": [ { "name": "max_demand", "peak_kw": 46.0, "cost_usd": 920.0 } ],
  "total_usd": 5130.55, "tariff_id": "demo_tariff_v1" }
```

### BacktestResult
```json
{ "dataset": "<label>", "month": "2026-07",
  "policies": { "without": "<Bill>", "timer": "<Bill>", "with": "<Bill>" },
  "checks": { "baseline_matches_raw": true, "energy_conserved": true, "rule_violations": 0 },
  "assumptions_id": "base" }
```

---

## 2. Seam 1 — REST + WebSocket (Frontend ↔ API)

### REST
| Method | Path | Body → Returns |
|---|---|---|
| GET | `/api/catalog` | → list[EquipmentType] |
| POST | `/api/kitchen` | KitchenConfig → `{ kitchen_id }` (builds both engine lanes, sends `sim_build` to the sim host; warm-up TBD) |
| GET | `/api/kitchen` | → `{ config: KitchenConfig, devices: list[Device], tariff: Tariff }` |
| PUT | `/api/kitchen/devices/{device_id}/importance` | `{ importance, limits }` → Device |
| PUT | `/api/kitchen/peak-cap` | `{ peak_mode, peak_cap_kw }` → Meter (`peak_cap_kw` required for `cap`, null for `minimize`) |
| POST | `/api/sim/control` | `{ action: "play" \| "pause" \| "reset", speed?: 120 }` → ClockState |
| POST | `/api/devices/{device_id}/command` | `{ action, value? }` → Command (manual click, `issued_by: owner`) |
| POST | `/api/events/customers` | `{ customers: 40, duration_min: 60 }` → ok (queued as a surge in the next `sim_tick`) |
| POST | `/api/decisions/{decision_id}/undo` | → Decision (status `undone`) |
| GET | `/api/decisions?limit=50` | → list[Decision] |
| POST | `/api/backtest/run` | `{ months: ["2026-07"], assumptions_id }` → `{ run_id: "run_0001" }` |
| GET | `/api/backtest/{run_id}` | → list[BacktestResult] |
| POST | `/api/chat` | `{ message }` → `{ chat_id: "chat_0001" }` (reply streams over WebSocket) |
| GET | `/api/proposals?status=pending` | → list[Proposal] |
| POST | `/api/proposals/{proposal_id}/confirm` | `{ confirm: true \| false }` → Proposal (owner confirmation from the UI) |
| PUT | `/api/kitchen/authority` | ClaudeAuthority → ok (owner only) |
| PUT | `/api/kitchen/preferences` | `{ text }` → ok |
| GET | `/api/context` | → Context |
| POST | `/api/context` | partial Context → ok (agents, header `X-Agent-Token`) |
| POST | `/api/context/crowd-effect` | `{ value, reason }` → ok (Concierge, `X-Agent-Token`) |
| GET | `/api/escalations?status=open` | → list[Escalation] |
| POST | `/api/escalations/{id}/resolve` | `{ option_id }` → Escalation (owner choice from the UI) |
| POST | `/api/agent-log` | AgentLog → ok (agents, `X-Agent-Token`) |
| GET | `/api/health` | → `{ ok, kitchen_impl, live_transport, store, hardware, sim_host }` (Azure health probe) |

Conventions: "→ ok" = `{ "ok": true }`. Errors: `{ "detail": "text" }` with 422 (RuleError, invalid body) or 404 (unknown id).
Health values: `kitchen_impl` fake | real · `live_transport` spacetime | ws · `store` convex | memory · `hardware` off | sim_bridge | esp32 ·
`sim_host` connected | offline.
ClockState = `{ playing, speed, sim_ts, tick_id, paused_reason, slowed_reason }` (the ws `clock` message without `type`).

### WebSocket `/ws` (server → client)
```json
{ "type": "tick", "data": "<TickState>" }
{ "type": "decision", "data": "<Decision>", "explanation": "text", "explanation_source": "ai | template" }
{ "type": "clock", "playing": true, "speed": 120, "sim_ts": "...", "tick_id": 1095, "paused_reason": null, "slowed_reason": null }
{ "type": "warning", "code": "cap_unreachable", "message": "text", "data": { "unavoidable_kw": 44.0, "peak_cap_kw": 40.0 } }
{ "type": "chat_delta", "chat_id": "...", "text": "partial text" }
{ "type": "chat_done", "chat_id": "..." }
{ "type": "backtest_progress", "run_id": "...", "month": "2026-07", "pct": 40 }
{ "type": "comparison", "data": "<LaneComparison>" }
{ "type": "proposal", "data": "<Proposal>" }
{ "type": "escalation", "data": "<Escalation>" }
{ "type": "context", "data": "<Context>" }
{ "type": "agent_log", "data": "<AgentLog>" }
```
`/ws` is the **viewer** socket (chat streaming, proposals, and everything when `LIVE_TRANSPORT=ws`). The sim host's hub uses a
separate socket, `/ws/hub` (section 8).
`paused_reason`: null | escalation | approval | hub_waiting (no `hub_report` within 2 real s) | sim_host_offline (no hub connected).
`slowed_reason`: null | escalation (clock dropped to `ESCALATION_SPEED` while Claude decides; `speed` shows the reduced value).
Ticks are sent for both lanes. The UI throttles rendering to ~4 per second.
`warning.data` per code: cap_unreachable `{ unavoidable_kw, peak_cap_kw }` · sim_host_offline `{ last_tick_id }` ·
hub_offline `{ device_id, hub_id }` · live_transport_down `{}` · store_down `{}`.
`warning.code`: cap_unreachable | sim_host_offline (no `/sim` tab connected; clock paused) |
hub_offline (no ESP32 reading for 30 s; that device falls back to simulated) |
live_transport_down (SpacetimeDB unreachable; switched to /ws) | store_down (Convex unreachable; switched to memory).

**Live transport.** With `LIVE_TRANSPORT=spacetime` (default) the runtime publishes ticks, comparison, feed and clock
to SpacetimeDB (section 5) and every UI tab subscribes there (the UI's only live source); chat, proposals and owner escalation choices still use REST + `/ws`.
With `LIVE_TRANSPORT=ws` every message above goes over `/ws` (offline fallback).

---

## 3. Seam 2 — Engine facade (API ↔ Engine, Python) — PROVISIONAL (engine TBD)

`from engine import Kitchen, run_backtest, compare_lanes, RuleError` — nothing else from the engine is public.
The engine does no I/O: HubReports and context come in and Commands go out as plain objects. The signatures below are what
the runtime and FakeKitchen build against; engine internals behind them are Kritazya's open decision.

| Call | Returns | Notes |
|---|---|---|
| `Kitchen(config, tariff, control, seed)` | Kitchen | `tariff`: Tariff (section 1). `control`: `"without"` or `"with"`. |
| `warm_up(...)` | None | Gives the forecaster history before the live run. Source and signature **TBD (Kritazya)**; FakeKitchen accepts any args. |
| `step(minutes, hub_report)` | TickState | Meters this lane's HubReport for the minute just simulated; replans every 5 sim min; returns `new_commands` to deliver next tick. |
| `ingest_reading(reading)` | Device | Overrides that device's power in the next `step` with a measured Reading; `source` becomes measured. `with` lane only. |
| `owner_command(device_id, action, value)` | Command | Manual click. Owner always wins; the engine won't override it for 30 sim min. Returned in the next step's `new_commands`, delivered in the following `sim_tick`. |
| `set_importance(device_id, importance, limits)` | Device | Raises `RuleError` for unsafe limits. |
| `set_peak_cap(peak_mode, peak_cap_kw)` | Meter | `with` lane decisions only; raises `RuleError` for `cap` without a number |
| `undo(decision_id)` | Decision | Reverts and protects that device from the engine for 30 sim min. |
| `set_context(context)` | None | Merges context; used from the next step. Plain object, no I/O. |
| `set_authority(authority)` · `set_preferences(text)` | None | `with` lane only |
| `open_escalations()` | list[Escalation] | |
| `resolve_escalation(escalation_id, option_id, resolved_by, rationale)` | Escalation | Validates against authority: `claude` + outside authority → status `awaiting_owner` (runtime makes a Proposal); `owner` may pick any generated option; past the deadline → default applied by the engine itself. |
| `forecast(horizon_min)` | list[float] | kW per 15 min. |
| `what_if(device_id, action, value, at)` | Effect `{peak_before_kw, peak_after_kw, saving_usd}` | No state change. For the AI. |
| `snapshot()` | `{ config, devices, meter, context, recent_decisions, open_escalations }` | Per lane; the runtime and AI use the `with` lane |
| `run_backtest(months, assumptions_id, on_progress)` | list[BacktestResult] | Module-level function. |
| `compare_lanes(without, with_)` | LaneComparison | Module-level function over two TickStates. |
| `RuleError` | exception | Raised for unsafe limits or moves. API maps it to HTTP 422. |

`FakeKitchen` (in `backend/fakes/`) implements every call above with canned results from `contracts/fixtures/facade/`.
Customer arrivals are simulated in the browser (section 9); surges reach them through `sim_tick.surges`.

---

## 4. AI tools (Claude tool use, implemented by the API on top of the facade)

| Tool | Calls | Notes |
|---|---|---|
| `get_kitchen_state` | `snapshot()` | |
| `get_forecast` | `forecast(120)` | Input `{}` |
| `explain_decision` | decision from `snapshot()` | Input `{ decision_id }`. Returns facts; the AI writes the sentence |
| `what_if` | `what_if(...)` | Input `{ device_id, action, value, at }`. For "what if I delay the dishwasher?" |
| `get_bill` | `snapshot()` meter, or a stored engine Bill / BacktestResult | Input `{ period: "YYYY-MM" }`. Never computed by the agent or the store |
| `propose_importance_change` | — | Input `{ device_id, importance, limits, summary }` → Proposal (`kind: importance`) |
| `propose_peak_cap_change` | — | Input `{ peak_mode, peak_cap_kw, summary }` → Proposal (`kind: peak_cap`) |
| `propose_escalation_choice` | — | Input `{ escalation_id, option_id, summary }` → Proposal (`kind: resolve_escalation`) when the owner says "do option 2" |
| `propose_undo` | — | Input `{ decision_id, summary }` → Proposal (`kind: undo_decision`) |
| `propose_customer_event` | — | Input `{ customers, duration_min, start_sim_ts, summary }` → Proposal (`kind: customer_event`), applied as a surge |

| `get_context` | `snapshot()` context | |
| `get_escalation` | `open_escalations()` | Options with engine numbers |
| `choose_escalation_option` | → runtime → `resolve_escalation(..., "claude", rationale)` | Input is an `option_id` from the offered list (enum-constrained). Code validates authority |
| `set_crowd_effect` | → `POST /api/context/crowd-effect` | Input is a category (enum), never a number |

Rules:
- The AI may only quote numbers that came back from a tool.
- Two bounded tools change state: `choose_escalation_option` (an offered id, validated by code against the owner's authority)
  and `set_crowd_effect` (a category). Everything else is a Proposal.
- Apart from those two, the model has no tool that changes state. Every other change is a Proposal applied by code after an owner confirmation:
  UI Confirm (`POST /api/proposals/{id}/confirm`), an ASI:One card button, or a `confirm` / `yes` reply to the latest
  pending Proposal, detected by code in `agents/concierge.py`, not by the model.
- The same agent and tools serve the dashboard chat and the Fetch.ai uAgent (Agent Chat Protocol, ASI:One).

---

## 5. SpacetimeDB tables (live shared kitchen; module in `spacetime/`)

Current state only, small rows, one batched write per real tick. Fields mirror section 1.

| Table | Key | Fields | Written by |
|---|---|---|---|
| `live_tick` | `lane` | ts, tick_id, total_kw, block_avg_kw, month_peak_kw, peak_mode, peak_cap_kw, target_kw, energy_kwh_today, price_usd_per_kwh_now, cost_usd_today, cost_usd_month, customers_per_hour, indoor_temp_c, forecast_kw_json, forecast_ts | runtime |
| `tick_history` | `lane` + `ts` | ts, total_kw, block_avg_kw (last 180 sim minutes per lane; older rows deleted) | runtime |
| `live_device` | `key` = `"<lane>:<device_id>"` | key, lane, device_id, type_id, name, importance, state, power_kw, rated_kw, power_pct, source, physical_json (what the kitchen floor draws, for every tab) | runtime |
| `live_comparison` | single row (`id` = 0) | LaneComparison fields | runtime |
| `live_feed` | `decision_id` | lane, ts, device_id, action, value, status, reason_code, effect_json, explanation, explanation_source (last 50) | runtime |
| `live_clock` | single row (`id` = 0) | playing, speed, sim_ts, tick_id, paused_reason, slowed_reason, sim_host (connected \| offline) | runtime |
| `live_context` | single row (`id` = 0) | weather_summary, weather_label, prices_summary, prices_label, events_summary, events_label, crowd_effect | runtime |
| `live_escalation` | `escalation_id` | lane, status, problem_json, options_json, chosen_option_id, resolved_by, rationale (last 20) | runtime |
| `live_agent_log` | auto id | ts_real, from_agent, to_agent, kind, summary (last 300) | runtime |
| `surge_request` | auto id | customers, duration_min, requested_by (identity), created_at, consumed | any viewer |

| Reducer | Who may call | Does |
|---|---|---|
| `publish_ticks(payload_json)` | runtime identity only | Upserts live_tick, tick_history, live_device, live_comparison for both lanes. Payload: `{ live_tick: [2], tick_history: [2], live_device: [every device, both lanes], live_comparison: {…} }` |
| `publish_feed(decision_json)` | runtime identity only | Upserts a live_feed row (template text first, AI text later). Other `publish_*` / `log_agent` reducers also take the row as a JSON string |
| `set_clock(playing, speed, sim_ts, tick_id, paused_reason, slowed_reason, sim_host)` | runtime identity only | Updates live_clock |
| `publish_context(json)` · `publish_escalation(json)` · `log_agent(json)` | runtime identity only | Upserts / appends |
| `reset_all()` | runtime identity only | Clears live tables (new kitchen) |
| `request_surge(customers, duration_min)` | anyone | Inserts surge_request (customers 1 to 80, duration 15 to 120 min) |
| `consume_surge(id)` | runtime identity only | Marks a surge consumed |

Calls go through `backend/live/spacetime_client.py` (Kritazya), which the runtime uses. It calls reducers over HTTP (`POST /v1/database/<db>/call/<reducer>`, JSON array of args) and reads new
surge requests with the SQL endpoint each tick. The engine never sees SpacetimeDB.

---

## 6. Convex tables (durable records + ESP32 bridge; code in `convex/`)

| Table | Fields | Written by |
|---|---|---|
| `kitchens` | config (KitchenConfig), created_at | API on `POST /api/kitchen` |
| `decisions` | Decision fields + lane, explanation, explanation_source | runtime (batched once per real second) |
| `commands` | Command fields + lane, hub_id (null if simulated only), delivery: queued \| sent \| acked \| failed | runtime; ESP32 acks |
| `readings` | Reading | ESP32 via `devices:report` |
| `device_map` | hub_id, channel, device_id, scale | set up once per demo kitchen |
| `hubs` | hub_id, last_seen, firmware | ESP32 heartbeat |
| `proposals` | Proposal | API / agent |
| `bills` | Bill + lane | runtime at month end and on demand |
| `backtest_results` | BacktestResult + run_id | API after `run_backtest` |
| `device_blocks` | lane, device_id, block_start, avg_kw, source | runtime, every closed 15-min block (simulated and measured) |
| `escalations` | Escalation (final state) | runtime |
| `context_snapshots` | Context + ts | runtime, hourly |

| Function | Type | Caller |
|---|---|---|
| `commands:forDevice(hub_id)` | query (ESP32 subscribes) | ESP32 |
| `commands:ack(command_id, ok, applied_value, reason)` | mutation | ESP32 (same meaning as CommandAck) |
| `devices:report(reading)` | mutation | ESP32, and the runtime on behalf of the browser hub when `HARDWARE=sim_bridge` |
| `hubs:heartbeat(hub_id)` | mutation | ESP32 |
| `commands:enqueue({ command, lane, hub_id })` · `decisions:record({ decisions: [Decision + lane, explanation, explanation_source] })` · `proposals:upsert({ proposal })` · `bills:save({ bill, lane })` · `backtest:save({ run_id, results })` | mutation | runtime / API |

ESP32 fail safe: no Convex contact for 30 s → every load returns to normal operation. Runtime: no reading for a mapped
device for 30 s → that device falls back to simulated and a `hub_offline` warning is emitted.


---

## 7. S5 — Agent messages (Fetch uAgents)
| Model | Direction | Fields |
|---|---|---|
| `WeatherRequest` / `WeatherResponse` | concierge → weather → concierge | `lat, lon, hours` / `hourly[{ts, temp_c}], source, label` |
| `PriceRequest` / `PriceResponse` | concierge → grid → concierge | `region` (e.g. `"caiso_np15"`)`, hours` / `hourly[{ts, usd_per_kwh}], stress, source, label` |
| `EventsRequest` / `EventsResponse` | concierge → events → concierge | `lat, lon, radius_km, window_h` / `items[...]` (Context.events), `source, label` |
| Agent Chat Protocol | owner (ASI:One) ↔ concierge | Fetch standard; acknowledgements on every message |

### AgentLog (every agent message, for the Agent Network view)
```json
{ "ts_real": "...", "from_agent": "concierge", "to_agent": "weather", "kind": "request", "summary": "Forecast 6 h for 37.80,-122.44" }
```
`kind`: request | response | post | error. Agent names: concierge | weather | grid | events | claude | engine.
Responses are reshaped into Context and posted unchanged to `POST /api/context`.

---

## 8. S6 — Hub protocol (browser hub ↔ FastAPI, WebSocket `/ws/hub`)

The hub in the sim host tab (`frontend/src/hub/`) is the only client of `/ws/hub`. One JSON message per frame,
`{ "type": ..., ... }`. FastAPI owns time: the hub never steps on its own.

**Hub → server**
```json
{ "type": "hub_hello", "protocol": 1, "hub_id": "sim_hub", "role": "sim_host", "client": "wattwise-web/0.1" }
{ "type": "hub_report", "tick_id": 1095, "reports": { "without": "<HubReport>", "with": "<HubReport>" } }
```
**Server → hub**
```json
{ "type": "hub_welcome", "accepted": true, "reason": null, "tick_id": 0 }
{ "type": "sim_build", "kitchen_id": "k_01", "config": "<KitchenConfig>", "catalog": ["<EquipmentType>"],
  "devices": ["<Device>"], "seed": 42, "start_sim_ts": "2026-07-18T00:30:00Z" }
{ "type": "sim_tick", "tick_id": 1095, "sim_ts": "2026-07-17T19:14:00Z", "minutes": 1,
  "surges": [ { "surge_id": "s_0003", "customers": 40, "duration_min": 60 } ],
  "inputs": { "outdoor_temp_c": 27.5, "crowd_multiplier": 1.25, "is_open": true },
  "commands": ["<Command>"], "replay": false }
{ "type": "sim_control", "action": "play | pause | reset", "speed": 120, "paused_reason": null }
```
Rules:
- `sim_build.devices` is the roster only (`state: "off"`, 0 kW, no `physical`); the simulation sets real state on tick 1.
  `start_sim_ts` example = Friday 17 July 2026, 17:30 local.
- A surge appears once, in the `sim_tick` where it starts; the simulation keeps it active for `duration_min`.
- `hub_welcome.accepted: false` with `reason: "host_taken"` when another sim host is connected; that tab stays a viewer.
- Order inside one tick: the hub applies `commands` (each to its `lane`) → the simulation steps both lanes `minutes` minutes
  from `sim_ts` with the same customer stream + `surges` → the hub replies `hub_report` with the same `tick_id`; each HubReport's
  `ts` = `sim_ts + minutes`.
- The server sends tick *n + 1* only after `hub_report` *n* arrives (or the hub reconnects). No report within 2 real s →
  clock `paused_reason: hub_waiting`; socket closed → `sim_host_offline`. On reconnect the server re-sends `sim_build`, then
  replays every past `sim_tick` with `"replay": true` at full speed (same commands, same surges); the hub answers only the last
  replayed tick, and the engine is not re-stepped. The deterministic simulation lands in the same state.
- Speed only changes the server's send interval (`0.5 s × 120 / speed`); one tick is always 1 sim minute.
- Cadence: the hub reports every tick (needed for exact energy, 15-min peak blocks and smooth live charts); the engine meters
  every report and makes decisions on every 5th tick (`tick_id % 5 == 0`). Commands can therefore appear only in the tick after a
  decision tick, or after an owner action / escalation choice.
- `inputs` are physical facts from context (outdoor temperature, crowd multiplier, opening hours), never engine decisions.
  Missing context → the simulation's built-in summer-day curve and multiplier 1.0.
- The hub never sends numbers the simulation did not produce, and never receives forecasts or decisions, only Commands.

---

## 9. S7 — Appliance interface (simulation ↔ hub, TypeScript, inside the browser)
| Call | Returns | Caller | Notes |
|---|---|---|---|
| `appliance.step(minutes, inputs)` | void | simulation | Physics + customer-driven usage; seeded randomness only |
| `appliance.reading()` | Device | hub only | 0 ≤ `power_kw` ≤ `rated_kw` |
| `appliance.apply(command)` | CommandAck | hub only | Executes on / off / start / delay / reduce / restore within physical limits |

Only the simulation and the hub depend on this seam (both Ashirwad), so it may change on the `ashirwad` branch without a
contract sync; whatever reaches HubReport or CommandAck still follows section 1. Power models and the equipment catalog:
`docs/design/SIMULATION.md`. A real ESP32 is a second hub: Commands in through Convex, Readings out (section 6).
