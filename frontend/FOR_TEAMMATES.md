# What Kritazya and Suyog need from Ashirwad's side

From Ashirwad (frontend, simulation, Static Web Apps). Everything is on branch **`ashirwad`**. Owners follow `docs/ARCHITECTURE.md`. Kritazya has the engine brain, backtest and proof, SpacetimeDB and Container Apps. Suyog has the API, the run loop, Claude, the Fetch agents, Convex and the ESP32.

Each item below says what's ready on my side, what you need to do, and how to tell it worked.

---

## 1. Ready for you to use

### Simulation (`backend/engine/`)
**Files:**
- `devices.py`, `hub.py`, `customers.py`, `fake_hub.py`
- `backend/data/equipment_catalog.json`
- tests: `backend/tests/simulation/` (23 pass):
  `cd backend && python -m pytest tests/simulation -q`

**API:**

| Call | What it does |
|---|---|
| `build_devices(config, catalog, seed)` | Makes one `SimDevice` per unit; ids are `<type_id>_<n>`. |
| `Hub(devices)` | The simulated ESP32 hub. |
| `hub.advance(ts, minutes, orders, outdoor_temp_c)` | Steps every device forward. |
| `hub.report(ts)` | Returns a `HubReport`: `{ ts, total_kw, devices[{device_id, power_kw, state, source}], source: "simulated" \| "mixed" }`. |
| `hub.deliver(command)` | Takes a `Command`: `{ command_id, ts, device_id, action, value, decision_id, issued_by }`. |
| `hub.devices()` | Returns the devices' current view. |
| `hub.ingest_reading(device_id, power_kw)` | A real ESP32 reading: that device is measured on the next step only. |
| `CustomerSource(seed, profile=None, crowd_multiplier=1.0).events(ts, minutes, surges)` | Returns `[{ ts, minutes, arrivals, orders, customers_per_hour }]`. Each surge is `{ customers, duration_min, start_ts }`. |
| `FakeHub(config, catalog)` | A deterministic hub for engine tests. |

**Rules the simulation enforces:**
- `reduce` is clamped to the unit's `min_power_pct` and to the food-safety floor: refrigeration never goes below 50 %.
- `delay` pauses a job; the job still runs in full later.
- After a restore, owed energy is paid back.

**Catalog:**
- Each type now has `default_limits`; the Builder uses them.
- The kW figures are still **PLACEHOLDER**. Their `source_note` says so.

### Frontend (`frontend/`)
- `npm run dev:mock` runs the whole UI against an in-browser fake server: Builder, Live with the 3D floor, escalations, proposals, context, Agent Network and Proof.
- The fake server mirrors the contract. Use it to compare against what your real messages look like.
- `npm run dev` points at the real FastAPI on `:8000`. Vite proxies `/api` and `/ws`.

---

## 2. Suyog: API, run loop, Claude, agents, Convex, ESP32

### The run loop drives my simulation
I assume the run loop owns the hub. Please confirm.

What the loop needs to do each step:
1. Ask `CustomerSource.events(...)` for arrivals, once per step.
2. Pass the same `orders` to both lanes' `hub.advance(...)`.
3. Hand `hub.report(ts)` to the engine.
4. `hub.deliver(cmd)` each command the engine returns, on the `with` lane only.

**Worked when:** the dinner peak is about 44 kW with a 40 kW cap, and a +40 customer surge pushes the `without` lane to about 53 kW.

### REST endpoints the browser calls
From `frontend/src/transport/real.ts`. All are in CONTRACTS.md except the last row.

| Method | Path |
|---|---|
| GET | `/api/catalog` (please include `default_limits` per type) |
| POST / GET | `/api/kitchen` |
| PUT | `/api/kitchen/devices/{id}/importance` |
| PUT | `/api/kitchen/peak-cap` |
| PUT | `/api/kitchen/authority` |
| PUT | `/api/kitchen/preferences` (body `{ text }`) |
| POST | `/api/sim/control` |
| POST | `/api/devices/{id}/command` |
| POST | `/api/events/customers` |
| POST | `/api/decisions/{id}/undo` |
| GET | `/api/decisions?limit=` |
| POST | `/api/chat` |
| GET | `/api/proposals?status=` |
| POST | `/api/proposals/{id}/confirm` (body `{ confirm }`) |
| GET | `/api/context` |
| GET | `/api/escalations?status=` |
| POST | `/api/escalations/{id}/resolve` (body `{ option_id }`) |
| GET | `/api/health` (`hardware` drives the hardware badge) |
| POST / GET | `/api/backtest/run`, `/api/backtest/{run_id}` |
| GET | **`/api/backtest/{run_id}/proof`**: proposed, see Kritazya §3 |

**What the frontend assumes about these:**
- **Per-unit importance:** `POST /api/kitchen` takes importance per **type**. When the owner sets a unit differently, the Builder calls `PUT /api/kitchen/devices/{id}/importance` for that unit right after the build. That endpoint must work straight after `POST /api/kitchen` returns.
- **`KitchenConfig` fields:** it now sends `location`, `owner_preferences` and `authority`. Please accept them.
- **CORS:** allow the Static Web Apps origin. I'll send the URL once it's deployed.

### `/ws` messages the UI reads
`tick`, `decision`, `clock`, `warning`, `chat_delta`, `chat_done`, `backtest_progress`, `comparison`, `proposal`, `escalation`, `context`, `agent_log`.

What the UI relies on:
- **`clock`:** when an escalation is waiting for the owner, set `paused_reason: "escalation"`. The decision dialog says the clock is paused, and choosing an option resumes it.
- **`escalation`:**
  - Send the whole object on **every** status change: open → resolved, awaiting_owner or expired_default.
  - The card shows "Claude is choosing…" while it is `open`.
  - Include `rationale` and `resolved_by` (`claude` or `owner`).
  - The option with id `ask_owner` is drawn without a Choose button.
- **`comparison`:** `saved_today_usd` and `peak_avoided_kw` are shown exactly as sent. The browser never subtracts the lanes.
- **`agent_log`:** `from_agent` / `to_agent` ids that get their own node on the graph are `concierge`, `weather`, `grid`, `events`, `claude`, `engine` and `owner`. Any other id still works but is drawn on top of the Concierge.
- **`backtest_progress`:** the Proof screen waits for `pct: 100` before it fetches the results.
- **Also wanted:**
  - replay the current state when a client connects;
  - a "warning cleared" message (today a warning stays until the user dismisses it).

### Convex and ESP32
- **Measured readings:** a real reading should go through `hub.ingest_reading(device_id, power_kw)`, after the `device_map` scaling (bench W → kitchen kW). Readings feed the `with` lane only.
- **Device `source`:** set it to `"measured"` on that device, and the report's top-level `source` to `"mixed"`. The UI then labels the device **"measured (scaled)"**.
- **Health:** `GET /api/health` → `hardware` should say whether the ESP32 is live (`esp32`) or simulated.

### Demo mode (DEMO.md)
I'm mirroring the demo in the mock: Friday **17:30**, 120×, the Giants game at 19:05 in recorded context, and one escalation about 2 minutes in.

The real `DEMO_MODE=1` should produce the same start time, the scripted escalation, and recorded context labeled `recorded`.

---

## 3. Kritazya: engine, backtest / proof, SpacetimeDB, Container Apps

### Proof screen data (needs your OK)
`BacktestResult` alone can't fill the Proof screen without the browser doing arithmetic. So I've **proposed** `ProofExtras`, defined in `frontend/src/types/contracts.ts` and served by `GET /api/backtest/{run_id}/proof`:

| Field | What it holds |
|---|---|
| `tariff` | `{ id, name }`, the real tariff name |
| `audit` | `"cleared" \| "pending" \| "failed"`. **The UI hides all numbers unless it is `cleared`.** |
| `months[]` | `{ month, partial, saved_vs_without_usd, saved_vs_timer_usd }`. January has `partial: true`. |
| `totals` | 12-month bills per policy, plus both savings figures |
| `busiest_day` | `{ date, series[{ts, without_kw, with_kw}] at 15 min, peak_without_kw, peak_with_kw, peak_without_ts }` |
| `sensitivity[]` | `{ id, label, kind: "assumptions" \| "tariff", saved_usd_year, saved_pct, worst }`. The engine marks the worst case. |
| `replay` | `{ month, steps[] }`, hourly. Each step has `without_kw`, `timer_kw`, `with_kw` and each policy's **running bill so far** (`without_usd`, `timer_usd`, `with_usd`). The last step must equal that month's bill. |

**What I need from you:**
1. Agree to this shape, or send me yours, and add it to CONTRACTS.md.
2. Give me the exact **dataset label** from DATA_AND_PROOF.md, e.g. "DOE-calibrated restaurant profile (NREL ComStock)", inside `BacktestResult.dataset`.
3. Record the tariff id in DECISIONS.md.
4. Provide a **cached run for demo mode**, so the Proof screen fills instantly. Either a fixed `run_id`, or `GET /api/backtest/latest`.

### SpacetimeDB
- **Where my side stands:** `frontend/src/data/spacetime.ts` already converts every table in CONTRACTS.md §5 into UI messages: `live_tick`, `live_comparison`, `live_feed`, `live_clock`, `live_context`, `live_escalation` and `live_agent_log`.
  - `connectSpacetime` and `callRequestSurge` are stubs until the bindings exist.
  - The frontend turns SpacetimeDB on with `VITE_LIVE_TRANSPORT=spacetime`, `VITE_SPACETIME_URI` and `VITE_SPACETIME_DB`.
  - If the connection fails, it falls back to `/ws` and shows a `live_transport_down` warning.
- **What I need from you:**
  - the **generated TypeScript bindings**; commit them or tell me the command;
  - the hosted URI and DB name;
  - the exact `request_surge` reducer signature. I assume `(customers, duration_min)`.

### Contract types
- The frontend types are a hand-copied STUB until `npm run gen:types` works.
- That needs FastAPI's `/openapi.json`, plus `contracts/ws_messages.schema.json` at the repo root. Please add the schema file.

### Azure
- **Container Apps backend URL and wss URL:** I'll set them as build-time env for Static Web Apps.
- **Health probe:** `GET /api/health`, as in the contract.

---

## 4. Team decisions still open
- **Azure account:** whose Azure account and credits do we deploy Static Web Apps on?
- **Run loop:** who calls `hub.advance`? I'm assuming Suyog's run loop.
- **Placeholder kW figures:** they stay until someone has 20 minutes for the FSTC / ENERGY STAR lookups. I can do it if no one else does.
