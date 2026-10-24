# Contracts

The single source of truth for every shape shared between Frontend, API and Engine.
- JSON is snake_case. Units in field names. Timestamps ISO 8601 with timezone.
- Backend: Pydantic models in `backend/contracts/`. Frontend: types generated from OpenAPI + `contracts/ws_messages.schema.json`.
- Change this file in the same commit as any shape change, and tell the team (use the `contract-sync` subagent).

Contents: 1 Shared shapes · 2 Seam 1 (REST + WebSocket) · 3 Seam 2 (engine facade) · 4 AI tools

---

## 1. Shared shapes

### Importance
`"always_on" | "flexible" | "deferrable"`

### EquipmentType (catalog entry, read-only, from `backend/data/equipment_catalog.json`)
```json
{ "type_id": "dishwasher", "name": "Dishwasher", "category": "water_heating",
  "default_importance": "deferrable", "rated_kw": 6.0, "min_power_pct": null,
  "power_model": "job", "params": { "cycle_min": 30 }, "source_note": "FSTC / ENERGY STAR" }
```
`category`: cooling | refrigeration | cooking | water_heating | lighting | other.
`power_model`: fixed | cycling | thermal | demand_driven | job (see design/SIMULATION.md).

### ImportanceLimits (depends on importance)
```json
{ "always_on":  {},
  "flexible":   { "min_power_pct": 40, "max_reduce_min": 30 },
  "deferrable": { "max_delay_min": 60, "must_finish_by": "15:30" } }
```

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
  "tariff_id": "<openei-urdb-id>",
  "seed": 42 }
```
Count 0 = not in this kitchen. Each unit becomes a Device with id `<type_id>_<n>` (e.g. `hvac_1`, `hvac_2`).

### Device (live state of one unit)
```json
{ "device_id": "hvac_1", "type_id": "hvac", "name": "HVAC 1", "importance": "flexible",
  "state": "reduced", "power_kw": 4.8, "rated_kw": 12.0, "source": "simulated" }
```
`state`: off | on | reduced | waiting (deferred job queued) | running_job.

### HubReport (what the simulated ESP32 reports each tick)
```json
{ "ts": "2026-07-17T19:15:00Z", "total_kw": 38.2,
  "devices": [ { "device_id": "hvac_1", "power_kw": 4.8, "state": "reduced" } ],
  "source": "simulated" }
```

### Command (engine → hub → device)
```json
{ "command_id": "c_0192", "ts": "...", "device_id": "dishwasher_1",
  "action": "delay", "value": 20, "decision_id": "d_0041", "issued_by": "engine" }
```
`action`: on | off | start | delay (value = minutes) | reduce (value = power %) | restore.
`issued_by`: engine | owner (manual click).

### Decision (engine output)
```json
{ "decision_id": "d_0041", "ts": "...", "device_id": "dishwasher_1", "action": "delay", "value": 20,
  "reason_code": "avoid_new_peak", "inside_rules": true,
  "status": "executed",
  "effect": { "peak_before_kw": 46.0, "peak_after_kw": 40.0, "saving_usd": 120.0 } }
```
`status`: executed | awaiting_approval | approved | declined | expired | undone.
`reason_code`: avoid_new_peak | stay_under_cap | release_into_valley | catch_up | owner_override.
`effect` is computed by the engine. Nobody else changes it.

### Meter
```json
{ "ts": "...", "total_kw": 38.2, "block_avg_kw": 37.9, "block_start": "...",
  "month_peak_kw": 46.0, "peak_cap_kw": 40.0,
  "energy_kwh_today": 312.4, "cost_usd_today": 61.20, "cost_usd_month": 1830.55 }
```

### TickState (engine → API every step; API forwards to UI)
```json
{ "lane": "with", "ts": "...", "hub": "<HubReport>", "meter": "<Meter>",
  "customers_per_hour": 64, "new_decisions": ["<Decision>"], "forecast_kw": [38, 41, 44, 39] }
```
`forecast_kw`: next 2 h in 15-min steps; present only on re-plan ticks, otherwise null.

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
| POST | `/api/decisions/{decision_id}/approve` | `{ approve: true }` → Decision |
| POST | `/api/decisions/{decision_id}/undo` | → Decision (status `undone`) |
| GET | `/api/decisions?limit=50` | → list[Decision] |
| POST | `/api/backtest/run` | `{ months, assumptions_id }` → `{ run_id }` |
| GET | `/api/backtest/{run_id}` | → list[BacktestResult] |
| POST | `/api/chat` | `{ message }` → `{ chat_id }` (reply streams over WebSocket) |

### WebSocket `/ws` (server → client)
```json
{ "type": "tick", "data": "<TickState>" }
{ "type": "decision", "data": "<Decision>", "explanation": "text", "explanation_source": "ai | template" }
{ "type": "approval_request", "data": "<Decision>", "explanation": "text", "expires_at": "<sim ts>" }
{ "type": "clock", "playing": true, "speed": 120, "sim_ts": "...", "paused_reason": null }
{ "type": "warning", "code": "cap_unreachable", "message": "text", "data": { "unavoidable_kw": 44.0 } }
{ "type": "chat_delta", "chat_id": "...", "text": "partial text" }
{ "type": "chat_done", "chat_id": "..." }
{ "type": "backtest_progress", "run_id": "...", "month": "2026-07", "pct": 40 }
```
Ticks are sent for both lanes. The UI throttles rendering to ~4 per second.

---

## 3. Seam 2 — Engine facade (API ↔ Engine, Python)

`from engine import Kitchen, CustomerSource, run_backtest` — nothing else from the engine is public.

| Call | Returns | Notes |
|---|---|---|
| `Kitchen(config, tariff, control, seed)` | Kitchen | `control`: `"without"` or `"with"`. |
| `warm_up(days=21)` | None | Simulates past days with no control so the forecaster has history. |
| `step(minutes, events)` | TickState | Moves time. `events`: customer arrivals for this step (same list for both lanes). |
| `owner_command(device_id, action, value)` | Command | Manual click. Owner always wins; the engine won't override it for 30 sim min. |
| `set_importance(device_id, importance, limits)` | Device | Raises `RuleError` for unsafe limits. |
| `set_peak_cap(peak_cap_kw)` | Meter | |
| `approve(decision_id, approve)` | Decision | Executes or declines a pending decision. |
| `undo(decision_id)` | Decision | Reverts and protects that device from the engine for 30 sim min. |
| `forecast(horizon_min)` | list[float] | kW per 15 min. |
| `what_if(device_id, action, value, at)` | Effect `{peak_before_kw, peak_after_kw, saving_usd}` | No state change. For the AI. |
| `snapshot()` | `{ config, devices, meter, pending_decisions, recent_decisions }` | |
| `run_backtest(months, assumptions_id, on_progress)` | list[BacktestResult] | Module-level function. |
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
| `get_bill` | meter / store | |
| `propose_importance_change` | — | Returns a proposal; applied only after the owner clicks Confirm in the UI |
| `propose_peak_cap_change` | — | Same: owner confirms |
| `add_customer_event` | `/api/events/customers` | "We have a 40-person party at 7" |
The AI may only quote numbers that came back from a tool.
