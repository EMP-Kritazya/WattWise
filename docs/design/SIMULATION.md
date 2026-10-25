# Design: Simulation + Hub (owner: Ashirwad; runs in the browser, in the sim host tab)

## Principles
- Physical, not clever: appliances follow simple physics and usage; no optimisation here.
- Deterministic: same config + seed + the same sequence of `sim_tick`s → identical readings. No `Math.random()`, no
  `Date.now()` inside `src/sim/` or `src/hub/` (lint rule); one seeded PRNG per kitchen.
- Tick-driven: the simulation steps only when FastAPI sends a `sim_tick` (1 simulated minute). It has no clock of its own.
- One hub: every reading out and every command in goes through the hub (the swap point for a real ESP32).
- Blind to the engine: the simulation never sees forecasts, decisions, the cap or costs. It receives Commands and reports state.
- Physics has the last word: an appliance applies a command within its physical limits and acks what really happened.
- Sourced numbers: power values from FSTC / ENERGY STAR with `source_note`.

The simulated restaurant: appliances that draw power, customers that drive them, and one hub (ESP32-style controller) that
every appliance reports to. It runs only in the **sim host** tab (`/sim`); every other tab, and the UI in the sim host tab
itself, draws the kitchen from SpacetimeDB, not from this code.

```
 FastAPI ──sim_tick (commands, surges, inputs)──▶ HUB ──apply(command)──▶ appliances ◀── customers (seeded)
    ▲                                              │                          │
    └──────────── hub_report (HubReport × 2, acks) ◀── reading() ─────────────┘
```

## Parts
| Part | File | What it does |
|---|---|---|
| Equipment catalog | `backend/data/equipment_catalog.json` | Every equipment type (EquipmentType in CONTRACTS.md); served by `GET /api/catalog` and sent in `sim_build` |
| Appliances | `frontend/src/sim/appliances/` | One unit each, holding its current state as React state (power, mode, physical); computes its power each minute from its power model (Appliance interface, CONTRACTS.md §9) |
| Customers | `frontend/src/sim/customers.ts` | Seeded arrivals from an hourly profile × crowd multiplier + surges from `sim_tick` |
| Kitchen | `frontend/src/sim/kitchen.ts` | Builds both lanes (`without`, `with`) from `sim_build`; same customer stream for both |
| Hub | `frontend/src/hub/hub.ts` | Applies Commands, collects readings into a HubReport per lane, acks commands |
| Hub link | `frontend/src/hub/link.ts` | `/ws/hub` client: `hub_hello`, handles `sim_build` / `sim_tick` / `sim_control`, sends `hub_report` (CONTRACTS.md §8) |
| Mock server | `frontend/src/mocks/mockHubServer.ts` | Plays `contracts/fixtures/hub_protocol/server_to_hub.jsonl`, so the simulation runs without FastAPI |

## Equipment catalog (starting set)
Power values below are **placeholders**: replace each with a figure from FSTC test reports or ENERGY STAR specs
and record the source in `source_note`. Only electric equipment (gas appliances never affect the electric peak).

| type_id | Category | Default importance | Power model | Notes |
|---|---|---|---|---|
| hvac | cooling | flexible | thermal | Power from indoor vs. outdoor temperature |
| walk_in_cooler | refrigeration | flexible | cycling | Compressor cycles within a temperature band |
| reach_in_fridge | refrigeration | always_on | cycling | Too small to bother moving |
| freezer | refrigeration | always_on | cycling | Food safety |
| ice_machine | refrigeration | deferrable | job | Ice batches can be made earlier or later |
| fryer | cooking | always_on | demand_driven | Idle power + per-order cooking power |
| oven | cooking | always_on | demand_driven | |
| grill | cooking | always_on | demand_driven | |
| dishwasher | water_heating | deferrable | job | Cycle starts when enough dirty racks pile up |
| water_heater | water_heating | flexible | cycling | Can run at reduced power and recover later |
| lights | lighting | always_on | fixed | On during opening hours |
| kitchen_exhaust | other | always_on | fixed | Hood exhaust, make-up air and RTU supply fans; runs 24/7 (ComStock `fans`, 5.74 kW) |
| other_equipment | other | always_on | demand_driven | Plug and process load (holding cabinets, steamer, steam table, warmers, microwaves) |

`params` keys per power model are fixed by CONTRACTS.md (EquipmentType). Owner can change importance per device (with limits) in the Kitchen Builder, and the count per type (0 = not present).
Each type also carries `default_limits` (CONTRACTS.md) that must pass the engine's rules check: e.g. `walk_in_cooler` starts
flexible with `min_power_pct: 50` (food-safety floor), `hvac` flexible with 40, `dishwasher` deferrable with `max_delay_min: 60`.

## Power models
| Model | Rule each minute |
|---|---|
| `fixed` | `rated_kw` when on, 0 when off |
| `cycling` | On/off duty cycle that keeps a temperature inside a band; more door openings when busy → more on-time |
| `thermal` | One dining-room temperature per kitchen, shared by every HVAC unit. Simple RC model: `dT_in/dt = (T_out − T_in)/(R·C) − Q_cool/C`; unit runs to hold the setpoint. Outdoor temp from `sim_tick.inputs.outdoor_temp_c`, else a fixed summer-day curve. Cut item: fixed HVAC curve if short on time |
| `demand_driven` | `idle_kw` + `kw_per_order × orders_in_progress`, capped at `rated_kw` |
| `job` | Runs a fixed cycle (`rated_kw` for `cycle_min`) when triggered; trigger = dirty racks ≥ N (dishwasher) or ice level low (ice machine) |

## How Commands act on appliances (what the engine may ask for)
| Importance | Commands the engine may send | Appliance behaviour |
|---|---|---|
| `always_on` | none (the engine never commands them; owner clicks only) | – |
| `flexible` | `reduce` (value = power %), `restore` | Draws at most `value% × rated_kw` (a device already below that is unaffected); physics continues (temperature drifts), catch-up after `restore` |
| `deferrable` | `delay` (value = minutes), `start` | A delay holds the next job (idle) or the queued job (`waiting`); the job starts on `start` or by itself when the hold ends; `delay` 0 clears the hold; a running job cannot be delayed (`ack.reason: job_running`) |
The rules (limits, food-safety floor, deadlines) are enforced by the engine before a Command is sent; appliances only enforce physics.

## Customers
- Hourly profile by weekday (labeled "simulated customer flow"): lunch peak ~12:00–13:30, dinner peak ~18:30–20:30.
- Arrivals per minute: Poisson with the seeded PRNG, × `inputs.crowd_multiplier`, plus active surges (a surge arrives once in
  `sim_tick.surges` and stays active for its `duration_min`).
- One stream drives both lanes, so the two kitchens see the same customers.
- Customers → orders (cooking load) and dirty racks (dishwasher trigger).

## Closed hours and multi-day runs
A run is several days (`config.run_days`); the closed hours are simulated too, at max speed (CONTRACTS.md section 8, Day lifecycle).
The simulation reads only `sim_tick.inputs.is_open` and keeps every appliance's state across midnight and across days.
| `is_open: false` | Behaviour |
|---|---|
| Customers | none arrive; orders in progress finish |
| Cooking and other equipment (`demand_driven`: fryer, oven, grill, other_equipment) | off (0 kW) |
| Lights (`fixed`) | off |
| Kitchen exhaust (`fixed`, category `other`) | keeps running at `rated_kw` (ventilation runs around the clock) |
| Refrigeration (`cycling`: walk-in, reach-in, freezer) | keeps cycling at `duty_idle_pct` (no door openings) |
| Ice machine, dishwasher (`job`) | jobs still trigger and run (ice refills overnight; last dishwasher cycle after close) |
| Water heater (`cycling`) | standby duty |
| HVAC (`thermal`) | setback: setpoint + 4 °C while closed, back to `setpoint_c` 30 min before open |
`sim_tick.fast_forward: true` (always with `is_open: false`): step and report exactly as usual, but do not re-render appliance
React state per tick (update the view once per 15 sim minutes). Physics and reports are identical with or without it.

## Hub (simulated ESP32)
- Applies the tick's Commands first (each to its `lane`), then the kitchen steps, then the hub builds one HubReport per lane:
  every appliance's `reading()`, `total_kw` = exact sum, `power_pct`, `physical`, `customers_per_hour`, `ts = sim_ts + minutes`.
- Every Command gets a CommandAck in that lane's HubReport (`acks`), which the runtime passes to the engine.
- The hub is the truth of appliance state: applying a Command updates the appliance's React state, which re-renders the
  Simulation view in the sim host tab, and the next HubReport carries it to the backend.
- The hub reports every tick; the engine decides every 5th tick (CONTRACTS.md §8 Cadence).
- `hub_hello` refused (`host_taken`) → the tab stops simulating and shows "another sim host is running".
- The hub is the only thing the backend reads from and writes to, exactly how a real ESP32 hub works. A real ESP32 is a second
  hub reached through Convex (`docs/design/CONVEX_AND_ESP32.md`); its readings are merged by the runtime as `measured`.

## Warm-up history
The engine warms up from 4 weeks of history (`WarmUpHistory`: NREL ComStock, or the fixture history until then; ENGINE.md
section 0). The simulation starts cold from `sim_build` and never sees that history.

## Tests (`frontend/src/sim/__tests__`, Vitest)
Same seed + same tick stream → identical HubReports (byte equal) · `total_kw` = sum of devices · power never negative or above
rated · each Command gets exactly one ack · a reduce to 40 % caps the draw at 40 % of `rated_kw` for that minute · `delay` 0 clears a hold · a delayed job
starts no earlier than its delay · the fixture tick stream (`contracts/fixtures/hub_protocol/`) produces reports that pass the
fixture checker's shape checks.
