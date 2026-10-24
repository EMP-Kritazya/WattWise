# Contracts

The single source of truth for every shape shared between Frontend, API and Engine.
- JSON is snake_case. Units in field names. Timestamps ISO 8601 with timezone.
- Backend: Pydantic models in `backend/contracts/`. Frontend: types generated from OpenAPI + `contracts/ws_messages.schema.json`
  + SpacetimeDB generated bindings + Convex generated types. Nothing hand written.
- SpacetimeDB rows and Convex documents carry the same snake_case fields as the shapes below.
- Change this file in the same commit as any shape change, and tell the team (use the `contract-sync` subagent).

Contents: 1 Shared shapes · 2 S1 REST + WebSocket · 3 S2 Engine facade · 4 AI tools · 5 S3 SpacetimeDB ·
6 S4 Convex · 7 S5 Agent messages · 8 S6 Hub interface

---

## 1. Shared shapes

### Importance
`"always_on" | "flexible" | "deferrable"`

### EquipmentType (catalog entry, read-only, from `backend/data/equipment_catalog.json`)
```json
{ "type_id": "dishwasher", "name": "Dishwasher", "category": "water_heating",
  "default_importance": "deferrable", "rated_kw": 6.0, "min_power_pct": null,
  "power_model": "job", "params": { "cycle_min": 30 },
  "default_limits": { "max_delay_min": 60, "must_finish_by": "15:30" }, "source_note": "FSTC / ENERGY STAR" }
```
`default_limits`: the limits a new unit of this type starts with. They must pass `rules.py`
(a refrigeration device set to flexible needs `min_power_pct` ≥ 50).
`category`: cooling | refrigeration | cooking | water_heating | lighting | other.
`power_model`: fixed | cycling | thermal | demand_driven | job (see design/SIMULATION.md).

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
    { "type_id": "dishwasher", "count": 1, "importance": "deferrable", "limits": { "max_delay_min": 60, "must_finish_by": "15:30" } },
    { "type_id": "fryer", "count": 1, "importance": "always_on", "limits": {} }
  ],
  "peak_cap_kw": 40.0,
  "operating_hours": { "open": "10:00", "close": "22:00" },
  "location": { "lat": 37.80, "lon": -122.44, "label": "Marina, San Francisco" },
  "owner_preferences": "Keep the dining room comfortable during dinner service.",
  "authority": "<ClaudeAuthority>",
  "tariff_id": "<openei-urdb-id>",
  "seed": 42 }
```
Count 0 = not in this kitchen. Each unit becomes a Device with id `<type_id>_<n>` (e.g. `hvac_1`, `hvac_2`).

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
  "state": "reduced", "power_kw": 4.8, "rated_kw": 12.0, "source": "simulated" }
```
`state`: off | on | reduced | waiting (deferred job queued) | running_job.
`source`: simulated | measured. Only a device fed by a real ESP32 reading (`ingest_reading`) is measured.

### HubReport (what the simulated ESP32 reports each tick)
```json
{ "ts": "2026-07-17T19:15:00Z", "total_kw": 38.2,
  "devices": [ { "device_id": "hvac_1", "power_kw": 4.8, "state": "reduced", "source": "simulated" } ],
  "source": "simulated" }
```
Top level `source`: simulated | mixed (at least one device is measured).

### Reading (real ESP32 → Convex → runtime → engine)
```json
{ "hub_id": "esp32_1", "channel": 0, "device_id": "dishwasher_1", "ts": "...",
  "raw_w": 6.2, "scale": 1000, "power_kw": 6.2 }
```
`power_kw = raw_w × scale / 1000`. Bench loads draw watts, so each channel declares a `scale` in Convex
`device_map`; the UI labels such a device "measured (scaled)". Readings feed the `with` lane only.

### Command (engine → hub → device)
```json
{ "command_id": "c_0192", "ts": "...", "device_id": "dishwasher_1",
  "action": "delay", "value": 20, "decision_id": "d_0041", "issued_by": "engine" }
```
`action`: on | off | start | delay (value = minutes) | reduce (value = power %) | restore.
`issued_by`: engine | owner (manual click, or an owner confirmed action from the UI or ASI:One).

### Decision (engine output)
```json
{ "decision_id": "d_0041", "ts": "...", "device_id": "dishwasher_1", "action": "delay", "value": 20,
  "reason_code": "avoid_new_peak", "inside_rules": true,
  "status": "executed",
  "effect": { "peak_before_kw": 46.0, "peak_after_kw": 40.0, "saving_usd": 120.0 } }
```
`status`: executed | escalated (an Escalation handles this block) | undone.
There is no per-decision owner approval any more: anything outside the rules becomes an Escalation.
`reason_code`: avoid_new_peak | stay_under_cap | release_into_valley | catch_up | owner_override | escalation_choice.
`effect` is computed by the engine. Nobody else changes it.

### Context (Fetch agents → API → engine; numbers forwarded unchanged)
```json
{ "ts": "...",
  "weather": { "label": "live_api", "source": "open-meteo", "hourly": [ { "ts": "...", "temp_c": 24.1 } ] },
  "prices":  { "label": "live_api", "source": "caiso", "hourly": [ { "ts": "...", "usd_per_kwh": 0.31 } ], "stress": "high" },
  "events":  { "label": "live_api", "source": "<events api>",
               "items": [ { "name": "Giants vs Dodgers", "venue": "Oracle Park", "start": "...", "distance_km": 1.8, "expected_attendance": 40000 } ] },
  "crowd_effect": { "value": "medium", "set_by": "claude", "reason": "Game ends 22:00, 1.8 km away" } }
```
Partial posts merge. `label`: live_api | recorded (demo mode). `stress`: low | normal | high.
`crowd_effect.value`: none | small | medium | large → engine multiplies customer arrivals by 1.00 / 1.10 / 1.25 / 1.40.
Engine uses: weather → HVAC load and forecast; prices → energy cost and tie-breaks; crowd effect → customers.

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
Options and every number in them come from the engine. Food-safety breaks are never generated as options.
The default is the least-harm in-authority option (normally `accept_overrun`), else `ask_owner`. Unresolved at the deadline →
nothing extra is done (equivalent to the overrun), status `expired_default`.

### Meter
```json
{ "ts": "...", "total_kw": 38.2, "block_avg_kw": 37.9, "block_start": "...",
  "month_peak_kw": 46.0, "peak_cap_kw": 40.0,
  "energy_kwh_today": 312.4, "cost_usd_today": 61.20, "cost_usd_month": 1830.55 }
```

### TickState (engine → API every step; API forwards to UI)
```json
{ "lane": "with", "ts": "...", "hub": "<HubReport>", "meter": "<Meter>",
  "customers_per_hour": 64, "new_decisions": ["<Decision>"], "new_commands": ["<Command>"],
  "new_escalations": ["<Escalation>"], "indoor_temp_c": 22.4,
  "forecast_kw": [38, 41, 44, 39, 36, 35, 37, 40] }
```
`forecast_kw`: next 2 h in 15-min steps (8 values); present only on re-plan ticks, otherwise null.
`new_commands`: every Command the hub delivered this step (engine and owner). The runtime forwards the `with` lane's
commands for ESP32 mapped devices to Convex.

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
`status`: pending | confirmed | cancelled | expired. `confirmed_via`: ui | asi_one | null.
Applied by code (never by the model) when the owner confirms; the result is the normal facade call.

### Bill
```json
{ "period": "2026-07", "energy_kwh": 21840.0, "energy_cost_usd": 4210.55,
  "demand_charges": [ { "name": "max_demand", "peak_kw": 46.0, "cost_usd": 920.0 } ],
  "total_usd": 5130.55, "tariff_id": "<id>" }
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
| POST | `/api/kitchen` | KitchenConfig → `{ kitchen_id }` (builds both lanes, runs 21-day warm-up) |
| GET | `/api/kitchen` | → KitchenConfig + list[Device] |
| PUT | `/api/kitchen/devices/{device_id}/importance` | `{ importance, limits }` → Device |
| PUT | `/api/kitchen/peak-cap` | `{ peak_cap_kw }` → Meter |
| POST | `/api/sim/control` | `{ action: "play" \| "pause" \| "reset", speed?: 120 }` → clock state |
| POST | `/api/devices/{device_id}/command` | `{ action, value? }` → Command (manual click, `issued_by: owner`) |
| POST | `/api/events/customers` | `{ customers: 40, duration_min: 60 }` → ok |
| POST | `/api/decisions/{decision_id}/undo` | → Decision (status `undone`) |
| GET | `/api/decisions?limit=50` | → list[Decision] |
| POST | `/api/backtest/run` | `{ months, assumptions_id }` → `{ run_id }` |
| GET | `/api/backtest/{run_id}` | → list[BacktestResult] |
| POST | `/api/chat` | `{ message }` → `{ chat_id }` (reply streams over WebSocket) |
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
| GET | `/api/health` | → `{ ok, kitchen_impl, live_transport, store, hardware }` (Azure health probe) |

### WebSocket `/ws` (server → client)
```json
{ "type": "tick", "data": "<TickState>" }
{ "type": "decision", "data": "<Decision>", "explanation": "text", "explanation_source": "ai | template" }
{ "type": "clock", "playing": true, "speed": 120, "sim_ts": "...", "paused_reason": null }
{ "type": "warning", "code": "cap_unreachable", "message": "text", "data": { "unavoidable_kw": 44.0 } }
{ "type": "chat_delta", "chat_id": "...", "text": "partial text" }
{ "type": "chat_done", "chat_id": "..." }
{ "type": "backtest_progress", "run_id": "...", "month": "2026-07", "pct": 40 }
{ "type": "comparison", "data": "<LaneComparison>" }
{ "type": "proposal", "data": "<Proposal>" }
{ "type": "escalation", "data": "<Escalation>" }
{ "type": "context", "data": "<Context>" }
{ "type": "agent_log", "data": "<AgentLog>" }
```
Ticks are sent for both lanes. The UI throttles rendering to ~4 per second.
`warning.code`: cap_unreachable | hub_offline (no ESP32 reading for 30 s; that device falls back to simulated) |
live_transport_down (SpacetimeDB unreachable; switched to /ws) | store_down (Convex unreachable; switched to memory).

**Live transport.** With `LIVE_TRANSPORT=spacetime` (default) the runtime publishes ticks, comparison, feed and clock
to SpacetimeDB (section 5) and the UI subscribes there; chat, proposals and owner escalation choices still use REST + `/ws`.
With `LIVE_TRANSPORT=ws` every message above goes over `/ws` (offline fallback).

---

## 3. Seam 2 — Engine facade (API ↔ Engine, Python)

`from engine import Kitchen, CustomerSource, run_backtest, compare_lanes, RuleError` — nothing else from the engine is public.
The engine does no I/O: readings come in and commands go out as plain objects.

| Call | Returns | Notes |
|---|---|---|
| `Kitchen(config, tariff, control, seed)` | Kitchen | `control`: `"without"` or `"with"`. |
| `warm_up(days=21)` | None | Simulates past days with no control so the forecaster has history. |
| `step(minutes, events)` | TickState | Moves time. `events`: customer arrivals for this step (same list for both lanes). Includes `new_commands`. |
| `ingest_reading(reading)` | Device | Uses a measured Reading for that device's power on the next step; `source` becomes measured. `with` lane only. |
| `owner_command(device_id, action, value)` | Command | Manual click. Owner always wins; the engine won't override it for 30 sim min. |
| `set_importance(device_id, importance, limits)` | Device | Raises `RuleError` for unsafe limits. |
| `set_peak_cap(peak_cap_kw)` | Meter | |
| `undo(decision_id)` | Decision | Reverts and protects that device from the engine for 30 sim min. |
| `set_context(context)` | None | Merges context; used from the next step. Plain object, no I/O. |
| `set_authority(authority)` · `set_preferences(text)` | None | `with` lane only |
| `open_escalations()` | list[Escalation] | |
| `resolve_escalation(escalation_id, option_id, resolved_by, rationale)` | Escalation | Validates against authority: `claude` + outside authority → status `awaiting_owner` (runtime makes a Proposal); `owner` may pick any generated option; past the deadline → default applied by the engine itself. |
| `forecast(horizon_min)` | list[float] | kW per 15 min. |
| `what_if(device_id, action, value, at)` | Effect `{peak_before_kw, peak_after_kw, saving_usd}` | No state change. For the AI. |
| `snapshot()` | `{ config, devices, meter, pending_decisions, recent_decisions }` | |
| `run_backtest(months, assumptions_id, on_progress)` | list[BacktestResult] | Module-level function. |
| `compare_lanes(without, with_)` | LaneComparison | Module-level function over two TickStates. |
| `RuleError` | exception | Raised for unsafe limits or moves. API maps it to HTTP 422. |
| `CustomerSource(seed, profile)` | source | Seeded customer arrivals. `.events(ts, minutes, surges)` → events for one step. The run loop creates **one** source and passes the same events to both lanes. |

`FakeKitchen` (in `backend/fakes/`) implements every call above with canned, contract-shaped results.

---

## 4. AI tools (Claude tool use, implemented by the API on top of the facade)

| Tool | Calls | Notes |
|---|---|---|
| `get_kitchen_state` | `snapshot()` | |
| `get_forecast` | `forecast(120)` | |
| `explain_decision` | decision from `snapshot()` | Returns facts; the AI writes the sentence |
| `what_if` | `what_if(...)` | For "what if I delay the dishwasher?" |
| `get_bill` | `snapshot()` meter, or a stored engine Bill / BacktestResult | Never computed by the agent or the store |
| `propose_importance_change` | — | Creates a Proposal (`kind: importance`) |
| `propose_peak_cap_change` | — | Proposal (`kind: peak_cap`) |
| `propose_escalation_choice` | — | Proposal (`kind: resolve_escalation`) when the owner says "do option 2" in chat; or the owner taps it in the UI |
| `propose_undo` | — | Proposal (`kind: undo_decision`) |
| `propose_customer_event` | — | Proposal (`kind: customer_event`): "We have a 40-person party at 7". Applied through the runtime's event queue |

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
| `live_tick` | `lane` | ts, total_kw, block_avg_kw, month_peak_kw, peak_cap_kw, cost_usd_today, customers_per_hour, forecast_kw_json | runtime |
| `tick_history` | `lane` + `ts` | ts, total_kw, block_avg_kw (last 180 sim minutes per lane; older rows deleted) | runtime |
| `live_device` | `lane:device_id` | lane, device_id, name, importance, state, power_kw, source | runtime |
| `live_comparison` | single row | LaneComparison fields | runtime |
| `live_feed` | `decision_id` | lane, ts, device_id, action, value, status, reason_code, effect_json, explanation, explanation_source (last 50) | runtime |
| `live_clock` | single row | playing, speed, sim_ts, paused_reason | runtime |
| `live_context` | single row | weather/prices/events summaries + labels, crowd_effect | runtime |
| `live_escalation` | `escalation_id` | lane, status, problem_json, options_json, chosen_option_id, resolved_by, rationale (last 20) | runtime |
| `live_agent_log` | auto id | ts_real, from_agent, to_agent, kind, summary (last 300) | runtime |
| `surge_request` | auto id | customers, duration_min, requested_by (identity), created_at, consumed | any viewer |

| Reducer | Who may call | Does |
|---|---|---|
| `publish_ticks(payload_json)` | runtime identity only | Upserts live_tick, tick_history, live_device, live_comparison for both lanes |
| `publish_feed(decision_json)` | runtime identity only | Upserts a live_feed row (template text first, AI text later) |
| `set_clock(playing, speed, sim_ts, paused_reason)` | runtime identity only | Updates live_clock |
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
| `commands:ack(command_id, ok)` | mutation | ESP32 |
| `devices:report(reading)` | mutation | ESP32, and the simulated hub when `HARDWARE=sim_bridge` |
| `hubs:heartbeat(hub_id)` | mutation | ESP32 |
| `commands:enqueue`, `decisions:record`, `proposals:upsert`, `bills:save`, `backtest:save` | mutation | runtime / API |

ESP32 fail safe: no Convex contact for 30 s → every load returns to normal operation. Runtime: no reading for a mapped
device for 30 s → that device falls back to simulated and a `hub_offline` warning is emitted.


---

## 7. S5 — Agent messages (Fetch uAgents)
| Model | Direction | Fields |
|---|---|---|
| `WeatherRequest` / `WeatherResponse` | concierge → weather → concierge | `lat, lon, hours` / `hourly[{ts, temp_c}], source, label` |
| `PriceRequest` / `PriceResponse` | concierge → grid → concierge | `region, hours` / `hourly[{ts, usd_per_kwh}], stress, source, label` |
| `EventsRequest` / `EventsResponse` | concierge → events → concierge | `lat, lon, radius_km, window_h` / `items[...]` (Context.events), `source, label` |
| Agent Chat Protocol | owner (ASI:One) ↔ concierge | Fetch standard; acknowledgements on every message |

### AgentLog (every agent message, for the Agent Network view)
```json
{ "ts_real": "...", "from_agent": "concierge", "to_agent": "weather", "kind": "request", "summary": "Forecast 6 h for 37.80,-122.44" }
```
Responses are reshaped into Context and posted unchanged to `POST /api/context`.

---

## 8. S6 — Hub interface (simulation ↔ brain, inside the engine)
| Call | Returns | Notes |
|---|---|---|
| `hub.report(ts)` | HubReport | Sums every device after the step; measured readings override simulated power for that device |
| `hub.deliver(command)` | None | Routes to the device; logs it; appears in `TickState.new_commands` |
| `hub.devices()` | list[Device] | Current state |
The brain never touches a device directly. A real ESP32 replaces the simulated hub's outputs through `ingest_reading()` and
receives `new_commands` through the runtime's device bridge; the interface above does not change.
