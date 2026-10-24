# Architecture

## The whole system
```
  OWNER                                   OWNER + JUDGES
  ASI:One chat (Fetch.ai)                 React dashboard (Azure Static Web Apps)
      | Agent Chat Protocol                   | REST: config, clicks,        | live subscription
      | via Agentverse                        | approvals, chat              | (every viewer, same kitchen)
 +----v---------------------------------------v----------+                   |
 |  API + AI   (Azure Container Apps, exactly 1 replica)  |                   |
 |  FastAPI · run loop (moves time) · two lanes           |                   |
 |  Claude agent + tools · Fetch.ai uAgent                |                   |
 |  store · SpacetimeDB publisher · device bridge · /ws   |                   |
 +----+-----------------------+---------------------+-----+                   |
      | Seam 2:               | Seam 4:             | Seam 3:                 |
      | engine facade         | records, commands,  | publish_ticks           |
      | (Python calls)        | readings            | (HTTP reducers)         |
 +----v-------------------+  +v------------------+ +v-----------------+       |
 | ENGINE (Kritazya)      |  | Convex            | | SpacetimeDB      |       |
 | no I/O                 |  | durable records   | | live shared      <-------+
 | SIMULATION: devices    |  | + ESP32 bridge    | | kitchen          |
 |   -> HUB (sim ESP32)   |  +---------^---------+ +------------------+
 | BRAIN: meter ->        |            | convex-esp32 (WiFi)
 |   forecaster -> decider|  +---------+---------+
 |   -> executor -> hub   |  | ESP32 hub         |
 | PROOF: replay+backtest |  | (optional, real   |
 +------------------------+  |  low-voltage      |
                             |  stand-in loads)  |
                             +-------------------+
```

## Who owns what
| Part | Owner | Builds | Never does |
|---|---|---|---|
| Engine brain + proof | Kritazya | Facade, meter, forecaster, decider, executor, rules, owed-energy ledger, `compare_lanes`, replay, backtest, data loading, contracts models | Talk to users, to Claude or to the network |
| Simulation | Ashirwad | Devices + power models, hub (simulated ESP32), customers, equipment catalog | Talk to users, to Claude or to the network |
| API + AI + integrations | Suyog | Server, endpoints, WebSocket, run loop (calls `step()`), approvals relay, proposals, Claude agent + tools, Fetch.ai uAgent, store, `FakeKitchen`, SpacetimeDB module + publisher, Convex, device bridge, ESP32 firmware | Decide or compute numbers |
| Frontend screens | Ashirwad | Kitchen Builder, Live floor + hub tile, two-lane chart, KPI row, decision feed, approval modal, banners, Proof page | Any calculation |
| Frontend data + chat | Suyog | Generated types, live data hook (SpacetimeDB / `/ws`), mock server, chat drawer + proposal cards | Any calculation |
| Cloud | Kritazya | Azure Container Apps (1 replica) + Static Web Apps, secrets, health probe | |

Simple test for any new task: **computes a number → engine. Moves data or talks to a person/AI → API. Visible on screen → frontend.
Simulated device behaviour → simulation. Talks to SpacetimeDB, Convex or the ESP32 → Suyog. Azure infrastructure → Kritazya.**

## How it works, one tick
1. The run loop (API) calls `kitchen.step(1)` for both lanes with the same customer events.
2. Each simulated device updates its power and reports to the **hub**.
3. The hub sums the restaurant's state (total kW, per-device kW, states).
4. The meter updates energy, the 15-minute demand average, the month peak and cost.
5. Every 5 simulated minutes the **brain** runs: forecast → decide → execute inside rules
   (outside rules → decision marked `awaiting_approval`).
6. The runtime calls `compare_lanes(without, with)`, publishes both ticks + the comparison to SpacetimeDB (or `/ws`),
   forwards the `with` lane's commands for ESP32 mapped devices to Convex, and buffers records for Convex.
7. The API sends approval requests to the owner (UI and ASI:One) and asks the AI to explain notable decisions.

A real ESP32 reading (when `HARDWARE=esp32`) enters through Convex → runtime → `kitchen.ingest_reading()` on the `with`
lane before the next step. The engine never touches the network.

## The two seams
- **Seam 1 (Frontend ↔ API):** JSON over REST + WebSocket. Frontend builds against a mock server until the API is ready.
- **Seam 2 (API ↔ Engine):** Python function calls with Pydantic objects (same shapes as the JSON). API builds against
  `FakeKitchen` until the engine is ready; switch with `KITCHEN_IMPL=real`.
- **Seam 3 (Runtime → SpacetimeDB → every browser):** live shared kitchen (CONTRACTS.md section 5). `LIVE_TRANSPORT=spacetime|ws`.
- **Seam 4 (Runtime ↔ Convex ↔ ESP32):** durable records and the hardware bridge (CONTRACTS.md section 6).
  `STORE=convex|memory`, `HARDWARE=off|esp32`.

Each backend owns one job: SpacetimeDB holds what ticks, Convex holds what is a record or a device. Nothing is the
source of truth in both. The engine's in-memory lanes are the source of truth for the simulation itself.

## Where the AI sits
Outside the decision loop. It reads engine state through tools, explains decisions, answers questions, and turns
owner requests ("never touch the fryer", "approve it") into **Proposals that the owner confirms**. Code, not the model,
applies a confirmed Proposal. If the AI is down, the kitchen runs exactly the same; explanations fall back to templates (labeled).

Two doors, one agent: the dashboard chat drawer and ASI:One. ASI:One reaches us through a Fetch.ai uAgent
(`agent/fetch_agent.py`, Agent Chat Protocol, registered on Agentverse). The full owner workflow (ask, see forecast and
plan, approve/undo, change rules, see savings) must work inside ASI:One with no custom frontend.

## Time
The engine has no clock. It only moves when `step(minutes)` is called. The run loop decides speed:
120× in the live demo, as fast as possible in backtest, paused while an approval is pending in demo mode.

## Hardware
The hub is simulated by default. With `HARDWARE=esp32`, a real ESP32 drives a few low-voltage stand-in loads mapped to
`device_id`s: it subscribes to its commands in Convex and reports readings back (`measured`, scaled). The simulated hub
calls the same Convex functions, so switching is one env var. The ESP32 starts only after the Phase 3 gate passes.

## Deploy
Azure Container Apps runs one image (FastAPI + run loop + uAgent) with **min = max replicas = 1**: the lanes and the run
loop live in memory, so scale to zero or scale out would break them. The frontend is on Azure Static Web Apps. SpacetimeDB
and Convex use their hosted clouds. Details: `docs/design/INTEGRATIONS.md`.

## Out of scope
Mains-powered equipment, real restaurant installs, multiple kitchens per deployment.
