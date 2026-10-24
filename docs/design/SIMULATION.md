# Design: Simulation (owner: Ashirwad; lives in `engine/`, so every engine rule applies)

## Principles
- Physical, not clever: devices follow simple physics and usage; no optimisation here.
- Deterministic: same config + seed + inputs → identical output. No clock: moves only on `step()`.
- One hub: every reading out and every command in goes through the hub interface (the swap point for a real ESP32).
- Sourced numbers: power values from FSTC / ENERGY STAR with `source_note`.
- No I/O and no network: simulation files live in `engine/` and follow every engine rule.

The simulated restaurant: devices that draw power, customers that drive them, and one hub box that every
device reports to. The frontend **draws** this kitchen; the engine **is** this kitchen.

## Parts
| Part | File | What it does |
|---|---|---|
| Equipment catalog | `data/equipment_catalog.json` | Every equipment type the owner can add (EquipmentType in CONTRACTS.md) |
| Devices | `engine/devices.py` | One object per unit; computes its power each step from its power model |
| Customers | `engine/customers.py` | `CustomerSource`: seeded arrivals from an hourly profile + surge events |
| Hub | `engine/hub.py` | Collects every device's power each step (HubReport); delivers Commands to devices |
| Kitchen | `engine/kitchen.py` | Builds devices from KitchenConfig, wires hub + brain, exposes the facade |

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

Owner can change importance per device (with limits) in the Kitchen Builder, and the count per type (0 = not present).
Each type also carries `default_limits` (CONTRACTS.md) that pass `rules.py`: e.g. `walk_in_cooler` starts flexible with
`min_power_pct: 50` (food-safety floor), `hvac` flexible with 40, `dishwasher` deferrable with `max_delay_min: 60`.

## Power models
| Model | Rule each step |
|---|---|
| `fixed` | `rated_kw` when on, 0 when off |
| `cycling` | On/off duty cycle that keeps a temperature inside a band; more door openings when busy → more on-time |
| `thermal` | Simple RC model: `dT_in/dt = (T_out − T_in)/(R·C) − Q_cool/C`; unit runs to hold the setpoint. Outdoor temp from a fixed daily curve (summer day). Cut item 3: replace with a fixed HVAC curve if short on time |
| `demand_driven` | `idle_kw` + `kw_per_order × orders_in_progress`, capped at `rated_kw` |
| `job` | Runs a fixed cycle (`rated_kw` for `cycle_min`) when triggered; trigger = dirty racks ≥ N (dishwasher) or ice level low (ice machine) |

## Importance behaviour (what the engine is allowed to do)
| Importance | Engine may | Limits |
|---|---|---|
| `always_on` | nothing | – |
| `flexible` | reduce power to `min_power_pct` for up to `max_reduce_min` | Never stops. Energy not used is **owed** (`owed_kwh` ledger, ENGINE.md 6b) and paid back the same day, so daily energy is conserved |
| `deferrable` | delay a job start | Up to `max_delay_min`, and must finish by `must_finish_by` |

## Customers
- Hourly profile by weekday (synthetic, labeled "simulated customer flow"): lunch peak ~12:00–13:30, dinner peak ~18:30–20:30.
- `CustomerSource(seed, profile).events(ts, minutes, surges)` returns arrivals for this step (Poisson, seeded).
- Surge events from the UI ("+40 customers for 60 min") are added on top.
- The run loop creates **one** source and passes identical events to both lanes.

## Hub (simulated ESP32) — the swap point
Interface (CONTRACTS.md section 8): `report(ts)`, `deliver(command)`, `devices()`. The brain uses nothing else.
- `engine/fake_hub.py` (Phase 1): same interface, constant/sine power, honours commands trivially. Kritazya builds the
  brain against it until the real devices exist.
- Each step: every device reports `{device_id, power_kw, state}`; the hub sums them into a HubReport.
- Commands from the engine (or owner clicks) go **through the hub** to the device. The hub logs every command.
- The hub is the only thing the brain reads from and writes to, which is exactly how a real ESP32 hub would work.

### Context inputs
`step()` receives the outdoor temperature (from context) for the thermal model and the crowd multiplier for customers.
No context → the fixed summer-day curve and multiplier 1.0.

### Bridge test without hardware (`HARDWARE=sim_bridge`)
The runtime sends the simulated hub's readings for mapped devices to Convex `devices:report` and routes their commands
through Convex `commands`, exactly as for a real ESP32. When this works, plugging in the ESP32 changes nothing upstream.

### Optional real ESP32 (`HARDWARE=esp32`)
- A real ESP32 drives a few low-voltage stand-in loads (small 5 to 12 V fans or LED strips, never mains), each mapped to a
  `device_id` in Convex `device_map` with a `scale` (bench watts → kitchen kW).
- The runtime forwards the `with` lane's Commands for mapped devices to Convex; the ESP32 receives them pushed through
  `convex-esp32` and acks. Its INA219 readings come back as Readings and enter the engine through `ingest_reading()`
  (`source: measured`, shown as "measured (scaled)").
- The engine's hub interface does not change, and the engine never talks to the network. Design: `docs/design/CONVEX_AND_ESP32.md`.

## Warm-up history
`warm_up(days=21)`: runs the configured kitchen for 21 simulated days with no control, at full speed, before the
demo starts. This gives the forecaster history that matches **this** kitchen's equipment.

## Determinism
Every random draw (customers, cycling phase) uses the kitchen seed. Same config + seed → identical run.
