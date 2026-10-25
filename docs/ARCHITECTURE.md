# Architecture

## The system
```
 OWNER (phone)                 OWNER + JUDGES (browsers) ── React app on Azure Static Web Apps                     [Ashirwad]
 ASI:One chat                  ┌───────────────────────────────────────────────────────────────────────────────┐
     │ Agent Chat Protocol     │ UI (every tab): Live floor, energy + cost, charts, feed, escalations, chat     │
     │                         │   reads live state ONLY from SpacetimeDB; actions via REST                    │
     │                         │ SIM HOST (exactly one tab, /sim):                                             │
     │                         │   SIMULATION (appliances, physics, customers, both lanes)                     │
     │                         │        ⇅ readings / apply(command)                                            │
     │                         │   HUB (the one ESP32-style controller)                                        │
     │                         └──────┬─────────────────────────▲──────────────────────▲───────────────────────┘
     ▼                                │ hub_report (+ acks)     │ sim_tick (+ commands) │ live subscription
 ┌──── FETCH AGENTS (Agentverse) ─┐   │  WebSocket /ws/hub      │                       │ + surge buttons
 │ Concierge (chat, Claude) ·     │   │                         │                       │   (request reducer)
 │ Weather · Grid · Events [Suyog]│   │                         │                       │
 └──────┬─────────────────────────┘   │                         │                       │
        │ periodic context (REST)     │                         │                       │
 ┌──────▼────── BACKEND · Azure Container Apps, 1 replica ──────┴───────────────┐       │
 │ API (FastAPI: REST, /ws/hub, /ws fallback)                                   │       │   [Suyog]
 │ RUNTIME: CLOCK (1 sim min per tick, 120× default) · hub link · two lanes ·   │       │
 │          escalations → Claude · proposals · device bridge                    │       │
 │ CLAUDE agent (explain, answer, propose, pick an escalation option id)        │       │
 │      │ engine facade (Python calls, plain objects)                           │       │
 │ ┌────▼──────── ENGINE (no I/O) ─────────────────────────────────────────┐    │       │   [Kritazya]
 │ │ meter → forecaster(+context) → decider (replans every 5 sim min)      │    │       │
 │ │ → escalation (when no in-preference move holds the cap) → commands    │    │       │
 │ │ rules · ledger · compare_lanes · replay/backtest  (design/ENGINE.md)  │    │       │
 │ └───────────────────────────────────────────────────────────────────────┘    │       │
 │ LIVE client ── HTTP reducers ───────────────────────────────────────────────┼───────┴──▶ SpacetimeDB  [Kritazya]
 │ STORE + DEVICE BRIDGE ──────────────────────────────────────────────────────┼──────────▶ Convex       [Suyog]
 └──────────────────────────────────────────────────────────────────────────────┘                ▲ convex-esp32
                                                                                        real ESP32 (optional)
```

## Parts and their boundaries
| Part | Lives in | Owner | Does | Never does |
|---|---|---|---|---|
| **Simulation** | `frontend/src/sim/` | Ashirwad | Appliance power models and physical state (temperatures, racks, ice, orders), seeded customer flow, both lanes; steps exactly once per `sim_tick` | Decide, read the engine, read the wall clock, use unseeded randomness |
| **Hub** | `frontend/src/hub/` | Ashirwad | The single ESP32-style controller: collects every appliance reading into a HubReport per lane, applies Commands to appliances (clamped to physical limits), acks them, speaks the hub protocol over `/ws/hub` | Decide, compute cost or forecasts |
| **UI** | `frontend/src/screens/`, `src/data/` | Ashirwad | Draws the kitchen, energy, current cost, charts, feed, escalations, chat | Simulate, compute, import `src/sim` or `src/hub` |
| **API + runtime** | `backend/api/`, `backend/runtime/` | Suyog | Owns the clock; drives the hub tick by tick; calls the engine; publishes live state; relays escalations to Claude; proposals; bridges | Compute numbers, decide |
| **Claude agent** | `backend/agent/` | Suyog | Explains, answers, proposes; picks one engine option id when the engine escalates | Produce numbers, apply anything itself |
| **Fetch agents** | `agents/` | Suyog | Fetch weather, prices, events on a fixed interval; Concierge chat in ASI:One | Compute or retype numbers |
| **Engine** | `backend/engine/` | Kritazya | Every number: energy, cost (real tariff), forecasts, decisions, escalation options; validates every choice | I/O of any kind, call Claude |
| **Live layer** | `spacetime/`, `backend/live/` | Kritazya | SpacetimeDB module + Python client; the UI's only live data source | Business logic in reducers |
| **Convex + ESP32** | `convex/`, `firmware/` | Suyog | Durable records, device map, real ESP32 bridge | Decide |

### Boundary rules
1. **The hub is the only door to the appliances.** The engine sees the kitchen only as HubReports (current state per lane) and
   changes it only with Commands, which travel runtime → `sim_tick` → hub → appliance. The simulation never sees the engine.
   A real ESP32 is a second hub with the same Command and Reading shapes (through Convex).
2. **FastAPI owns time.** One `sim_tick` = 1 simulated minute; at 120× a tick is sent every 0.5 real s. The simulation steps only
   when a tick arrives. The engine replans every 5 sim minutes. Commands produced at tick *n* are delivered in tick *n + 1*.
3. **Charts from SpacetimeDB, appliances from the hub.** The main screen toggles between a **Charts** view and a **Simulation**
   view. Charts (energy, cost, peaks, forecast, comparison) always read SpacetimeDB, the engine's published results, in every tab.
   The Simulation view draws appliances through one hook: in the sim host tab it shows the hub's live React state (the source of
   truth for appliance state); in viewer tabs the same components draw `live_device` rows. Actions go over REST; surges through
   the `request_surge` reducer. `LIVE_TRANSPORT=ws` sends the same rows over `/ws` (offline fallback).
4. **Exactly one sim host.** The first `/sim` tab whose `hub_hello` is accepted runs both lanes. Others are refused
   (`host_taken`) and stay plain viewers. Host gone → the clock pauses (`paused_reason: sim_host_offline`) and resumes on reconnect.
5. **The engine does no I/O.** It gets HubReports and context as plain objects through the facade and returns TickStates.
   "The engine contacts Claude" means: the engine emits an Escalation; the runtime calls Claude and hands the chosen id back.
6. **Claude only on escalation.** The engine handles every routine move within the owner's limits and preferences. Only
   when no such move holds the cap does it escalate: it ranks up to 3 evaluated alternatives, applies the best
   one within `ClaudeAuthority` at once (the fallback) and asks Claude once, who may switch to another option; the engine
   revalidates it; beyond the authority → owner confirmation; no answer by the deadline → the fallback stays.
7. **Context is periodic.** The Concierge fetches Weather, Grid and Events every `CONTEXT_INTERVAL_S` (default 600 real s)
   and on kitchen build, posts it unchanged, and the runtime passes the latest to the engine. The engine never waits for it.
8. **Two truths, no overlap.** The hub is the truth of appliance state. The engine is the truth of every computed number
   (energy, cost, forecasts, decisions). The engine returns results to the runtime; the live client (`backend/live/`) writes them to
   SpacetimeDB; the UI shows them.

Quick test: **computes a number → engine. Appliance behaviour → simulation. Collects readings or applies a command → hub.
Moves time, data or talks to a person, AI or agent → Suyog. Visible on screen → Ashirwad. Live tables → Kritazya.**

## Seams (each has a contract and a fake, so nobody waits for anybody)
| # | Seam | Form | Fake for independent work |
|---|---|---|---|
| S1 | UI ↔ API | REST (+ `/ws` fallback) | `frontend/src/mocks` REST handlers on `contracts/fixtures/rest/` (Ashirwad) |
| S2 | Runtime ↔ Engine | Python facade, plain objects | `backend/fakes/fake_kitchen.py` on `fixtures/facade/` (Suyog) |
| S3 | Runtime → SpacetimeDB → UI | `backend/live` client + tables/reducers + generated TS bindings | `fakes/fake_live.py`, `spacetime/seed.ts`, frontend mock live hook on `fixtures/spacetime/` (Kritazya / Ashirwad) |
| S4 | Runtime ↔ Convex ↔ ESP32 | Convex functions | `STORE=memory`, `HARDWARE=off` (Suyog) |
| S5 | Agents ↔ API, agent ↔ agent | REST + Fetch message models + Chat Protocol | `--recorded` mode per agent on `fixtures/agents/` (Suyog) |
| S6 | Hub ↔ API (the hub protocol) | WebSocket `/ws/hub`: `hub_hello`, `sim_build`, `sim_tick`, `hub_report`, `sim_control` | Frontend: `src/mocks/mockHubServer.ts` plays `fixtures/hub_protocol/server_to_hub.jsonl` (Ashirwad). Backend: `fakes/fake_hub_client.py` plays `hub_to_server.jsonl` (Suyog) |
| S7 | Simulation ↔ Hub (inside the browser) | TypeScript interface `Appliance`: `step()`, `reading()`, `apply()` | Ashirwad's own tests; nobody else depends on it |

All fakes read the same shared fixtures in `contracts/fixtures/` (built by the `fixture-builder` subagent), so the three
branches agree byte for byte when they merge.

## Five flows
**1. Tick (reflexes).** Every real tick the runtime: collects surges (SpacetimeDB requests + REST) → sends `sim_tick`
(sim_ts, 1 minute, surges, physical inputs, pending Commands for both lanes) → the hub applies the Commands, the simulation steps
1 minute, the hub replies `hub_report` (one HubReport per lane + command acks) → runtime merges any fresh ESP32 readings, calls
`step(1, report)` on both engine lanes → every 5 sim minutes the engine replans → TickStates (meter, decisions, `new_commands`,
escalations) → `compare_lanes` → one batched SpacetimeDB publish → `new_commands` queued for the next `sim_tick` → ESP32-mapped
Commands forwarded to Convex → store buffers records. No `hub_report` within 2 real s → the clock waits (`hub_waiting`).

**2. Context (senses).** Every `CONTEXT_INTERVAL_S` the Concierge asks Weather, Grid and Events → structured replies →
`POST /api/context` unchanged → runtime `set_context` on both lanes. Physical parts of it (outdoor temperature, crowd
multiplier) also go to the simulation inside `sim_tick.inputs`. Claude classifies events into `crowd_effect` (a category).
Every agent message is logged → SpacetimeDB `live_agent_log`.

**3. Escalation (judgment).** Engine finds a block over the cap with no move inside the owner's limits and preferences →
Escalation with up to 3 evaluated, harm-ranked alternatives, engine numbers for each, `within_authority` → the engine
applies the safe fallback (best-ranked option within authority, else accept_overrun) **at once** → runtime asks Claude (context + preferences + ranked
options) asynchronously → Claude returns an id → `resolve_escalation(...)` → engine revalidates on the latest state: within
authority and in time → it switches with the next tick; outside → rejection verdict and one Claude retry before deadline. No answer by the deadline → the fallback stays.
The clock keeps running at its speed throughout.

**4. Owner (control).** Dashboard REST or ASI:One chat → answers from engine tools → any change is a Proposal → owner confirms →
code applies via the facade. Manual device clicks → `owner_command()` on both lanes (same manual input, fair comparison) → Command in the next `sim_tick`.

**5. Build.** `POST /api/kitchen` → runtime builds both engine lanes → sends `sim_build` (config, devices, seed, start time) to the
sim host → the simulation creates both kitchens → `reset_all` + first publish to SpacetimeDB → play.
Before the first tick each engine lane gets `warm_up(history)`: 4 weeks of per-device 15-min blocks built from NREL ComStock
(scaled to the kitchen, label `calibrated_model`; the fixture history until that extract exists), so the forecast, the `minimize` target and month-to-date start realistic
(DATA_AND_PROOF.md, "Real data in the live product").

## Hub swap (simulated hub → real ESP32)
The engine only sees HubReports and emits Commands. `HARDWARE=esp32`: the runtime forwards the `with` lane's Commands for mapped
devices to Convex; the ESP32 executes them and reports Readings, which the runtime merges into that lane's HubReport as
`measured` (via `ingest_reading`). `HARDWARE=sim_bridge`: the runtime sends the browser hub's readings for mapped devices
through the same Convex functions, proving the drop-in without hardware. Every device's 15-min average lands in Convex `device_blocks`.

## Time
The runtime owns the clock: `sim_tick` every `0.5 s × 120 / speed` (speeds 1×, 30×, 120× default, 600×). The engine and the
simulation have no clock of their own. Paused while the hub is missing, manually (presenter / owner), or when the run is complete; never for an escalation or approval.
Escalation deadlines are in sim time; Claude's timeout is in real time. Backtest runs in Python at full speed without the browser.

**Days.** Cold start = build both lanes and `warm_up` them with 4 weeks of history in one call (no ticks), then run
`run_days` service days (KitchenConfig). Each day ticks at `speed` from open (day 1: `start_sim_ts`) to close; the closed hours are
ticked too, back to back at max speed (`phase: overnight`, `sim_tick.fast_forward: true`, `inputs.is_open: false`), so always-on
loads keep drawing and are billed. After the last day's close the clock stops (`paused_reason: run_complete`); the owner presses
**Continue +1 day** (`next_day`). A year is never run live: the backtest covers it (DATA_AND_PROOF.md).

**Claude at 120×.** At 120× one real second is two sim minutes, so an 8 s Claude call costs 16 sim minutes. The clock is never
slowed for it; instead:
1. **Escalate within 30 minutes of the risk.** The engine opens an escalation when a block starting in the next 30 sim min is
   still over the target after every in-rules move (deadline = `max(ts + 5, min(ts + 15, block start − 5))` sim min).
2. **Act first, ask second.** The engine applies the best safe option within the owner's authority the moment the escalation
   opens (accept_overrun if none is authorized); Claude's answer can only switch it, after the engine revalidates it on the latest state (safe, authorized, in time).
3. **Never wait.** Claude timeout 8 real s; on timeout the fallback simply continues. Manual pause/resume exists for judges and
   presenters; it is a runtime control the engine and the backtest never see.

## Deploy
Azure Container Apps: `backend` (API + runtime + engine, min = max = 1 replica) and `agents` (uAgents, 1 replica, always on).
Static Web Apps: frontend; the demo laptop keeps the `/sim` tab open. SpacetimeDB and Convex: hosted clouds.
Claude: Anthropic API, or Microsoft Foundry via env.

## Out of scope
Mains-powered equipment, real restaurant installs, multiple kitchens per deployment.
